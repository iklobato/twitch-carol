"""Topics cover the whole live: the topics prompt shows numbered 15-minute
blocks and speech from across the live, each block goes to one topic, and a
topic's blocks are what money, chat and follows are matched against."""

import json
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.follower_signals import topic_to_follows
from core.models import Channel, Insight, InsightType, Stream, TranscriptSegment
from tests.conftest import login_as
from tests.factories import (
    add_chat,
    add_event,
    add_insight,
    add_segment,
    make_channel,
    make_stream,
)
from tests.test_analysis_e2e import PromptAwareFakeLLM
from workers.analyze.pipeline import run_analysis

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

LIVE_MINUTES = 45
SEGMENT_EVERY_SECONDS = 120
SEGMENT_COUNT = 22
# Past the first 12 segments (0-22 min), the only speech the topics prompt
# used to show.
LATE_SPEECH_FROM = timedelta(minutes=30)
UNKNOWN_BLOCK = 99
FIRST_BLOCK = 1
SECOND_BLOCK = 2
LAST_BLOCK = 3
TWO_BLOCK_LIVE_MINUTES = 30
BLOCK = timedelta(minutes=15)
EARLY_SEGMENT_AT = 60
NEARER_SEGMENT_AT = 300
IN_SECOND_BLOCK_AT = 1200
CHEER_BITS = 500
CHEER_USD = 5.0
CHAT_IN_SECOND_BLOCK = 4
CHAT_SPREAD_SECONDS = 30


class BlockClaimingFakeLLM(PromptAwareFakeLLM):
    """Answers the topics prompt with block ids read from the prompt's block
    labels. "Deploy" also asks for block 1, already given to "Abertura", and
    "Abertura" asks for a block that was never shown."""

    def __init__(self) -> None:
        self.topics_prompt = ""

    def generate(self, prompt: str, max_tokens: int) -> str:
        if '"topics"' not in prompt:
            return super().generate(prompt, max_tokens)
        self.topics_prompt = prompt
        segment_ids, _ = self._candidates(prompt)
        blocks = [int(number) for number in re.findall(r"^B(\d+) \[", prompt, re.M)]
        topics = [
            {
                "name": "Abertura",
                "segment_ids": segment_ids[:1],
                "block_ids": [FIRST_BLOCK, UNKNOWN_BLOCK],
            },
            {"name": "Deploy", "segment_ids": segment_ids[-1:], "block_ids": blocks},
        ]
        return json.dumps({"topics": topics})


class AnalyzedLive:
    """A live with speech every two minutes, run through the analysis with
    BlockClaimingFakeLLM."""

    def __init__(self, db: Session, stream: Stream, llm: BlockClaimingFakeLLM) -> None:
        self._db = db
        self.stream = stream
        self.llm = llm

    def topic_blocks(self, name: str) -> list[dict[str, str]]:
        topic = self._db.scalars(
            select(Insight)
            .where(Insight.stream_id == self.stream.id)
            .where(Insight.type == InsightType.TOPIC)
            .where(Insight.content.startswith(name))
        ).one()
        return topic.evidence.get("blocks", [])

    def block_span(self, number: int) -> dict[str, str]:
        start = self.stream.started_at + BLOCK * (number - 1)
        return {"start": start.isoformat(), "end": (start + BLOCK).isoformat()}

    def late_segment_ids(self) -> set[int]:
        cutoff = self.stream.started_at + LATE_SPEECH_FROM
        return set(
            self._db.scalars(
                select(TranscriptSegment.id)
                .where(TranscriptSegment.stream_id == self.stream.id)
                .where(TranscriptSegment.started_at >= cutoff)
            )
        )


@pytest.fixture
def analyzed(db: Session) -> AnalyzedLive:
    stream = make_stream(db, make_channel(db), duration_minutes=LIVE_MINUTES)
    for index in range(SEGMENT_COUNT):
        add_segment(db, stream, index * SEGMENT_EVERY_SECONDS, f"fala {index}")
    llm = BlockClaimingFakeLLM()
    run_analysis(db, stream, llm)
    db.flush()
    db.refresh(stream)
    return AnalyzedLive(db, stream, llm)


def test_topics_prompt_labels_every_block_with_its_id_and_time(
    analyzed: AnalyzedLive,
) -> None:
    labels = re.findall(r"^B(\d+) \[\d\d:\d\d-\d\d:\d\d UTC\]", analyzed.llm.topics_prompt, re.M)
    assert labels == [str(FIRST_BLOCK), str(SECOND_BLOCK), str(LAST_BLOCK)]


def test_topics_prompt_offers_speech_from_the_end_of_the_live(
    analyzed: AnalyzedLive,
) -> None:
    offered, _ = analyzed.llm._candidates(analyzed.llm.topics_prompt)
    assert analyzed.late_segment_ids() & set(offered)


def test_block_already_given_to_a_higher_ranked_topic_is_not_given_again(
    analyzed: AnalyzedLive,
) -> None:
    expected = [analyzed.block_span(SECOND_BLOCK), analyzed.block_span(LAST_BLOCK)]
    assert analyzed.topic_blocks("Deploy") == expected


def test_block_the_model_was_never_shown_is_dropped(analyzed: AnalyzedLive) -> None:
    assert analyzed.topic_blocks("Abertura") == [analyzed.block_span(FIRST_BLOCK)]


class BlockTopicLive:
    """A 30-minute live with two topics whose cited speech is in the first
    minutes (as in production), "Primeiro" nearer to minute 20 by its speech,
    "Segundo" owning the second 15-minute block."""

    def __init__(self, db: Session, channel: Channel, stream: Stream) -> None:
        self._db = db
        self.channel = channel
        self.stream = stream

    def add_topic(self, name: str, segment_at: int, block_number: int) -> Insight:
        segment = add_segment(self._db, self.stream, segment_at, name)
        start = self.stream.started_at + BLOCK * (block_number - 1)
        block = {"start": start.isoformat(), "end": (start + BLOCK).isoformat()}
        evidence = {"segment_ids": [segment.id], "message_ids": [], "blocks": [block]}
        return add_insight(self._db, self.stream, InsightType.TOPIC, f"{name}\nx", evidence)

    def add_event_at(self, event_type: str, offset_seconds: int) -> None:
        event = add_event(
            self._db,
            self.stream,
            event_type,
            offset_seconds=offset_seconds,
            amount=CHEER_BITS,
        )
        event.payload = {"user_login": "baleia", "bits": CHEER_BITS}
        self._db.flush()


@pytest.fixture
def block_live(db: Session) -> BlockTopicLive:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=TWO_BLOCK_LIVE_MINUTES)
    live = BlockTopicLive(db, channel, stream)
    live.add_topic("Primeiro", NEARER_SEGMENT_AT, FIRST_BLOCK)
    live.add_topic("Segundo", EARLY_SEGMENT_AT, SECOND_BLOCK)
    return live


def test_money_in_a_topic_block_goes_to_that_topic_not_to_the_nearest_speech(
    api_client: TestClient, block_live: BlockTopicLive
) -> None:
    block_live.add_event_at("channel.cheer", IN_SECOND_BLOCK_AT)
    login_as(api_client, block_live.channel)
    body = api_client.get(f"/api/streams/{block_live.stream.id}/finance").json()
    assert body["by_topic"] == [{"name": "Segundo", "estimated_usd": CHEER_USD, "events": 1}]


def test_follow_in_a_topic_block_is_credited_to_that_topic(
    db: Session, block_live: BlockTopicLive
) -> None:
    block_live.add_event_at("channel.follow", IN_SECOND_BLOCK_AT)
    follows = topic_to_follows(db, block_live.channel.id)
    assert [(item.topic, item.follows) for item in follows] == [("Segundo", 1)]


def test_topic_detail_counts_the_chat_of_the_topic_blocks(
    api_client: TestClient, db: Session, block_live: BlockTopicLive
) -> None:
    second = db.scalars(
        select(Insight)
        .where(Insight.stream_id == block_live.stream.id)
        .where(Insight.content.startswith("Segundo"))
    ).one()
    add_chat(
        db,
        block_live.stream,
        CHAT_IN_SECOND_BLOCK,
        offset_seconds=IN_SECOND_BLOCK_AT,
        spread_seconds=CHAT_SPREAD_SECONDS,
    )
    login_as(api_client, block_live.channel)
    url = f"/api/streams/{block_live.stream.id}/topics/{second.id}"
    assert api_client.get(url).json()["messages_in_window"] == CHAT_IN_SECOND_BLOCK
