"""Money that lands outside every topic window goes to the nearest topic of the
same live, a moment inside two overlapping topics counts once (for the
higher-ranked one), and a live with no topic credits nothing. Same rule on the
live finance page, the channel page and the email digest (core.topics)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.digest import build_period
from core.models import Channel, DigestPeriod, InsightType, Stream
from tests.conftest import login_as
from tests.factories import (
    add_event,
    add_insight,
    add_segment,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

LIVE_MINUTES = 60
LIVE_STARTED_MINUTES_AGO = 3 * 24 * 60
SEGMENT_SECONDS = 60
OPENING_AT = 60
DEPLOY_AT = 2400
# Outside both padded windows (0-180s and 2340-2520s), 440s before Deploy.
BETWEEN_TOPICS_AT = 1900
OVERLAP_FIRST_AT = 300
OVERLAP_SECOND_AT = 320
INSIDE_BOTH_AT = 330
CHEER_BITS = 500
CHEER_USD = 5.0
DIGEST_MARGIN = timedelta(days=1)


class TopicLive:
    """One live whose topics are each cited by one speech segment, added in
    rank order."""

    def __init__(self, db: Session, channel: Channel, stream: Stream) -> None:
        self._db = db
        self.channel = channel
        self.stream = stream

    def add_topic(self, name: str, offset_seconds: int) -> None:
        segment = add_segment(
            self._db,
            self.stream,
            offset_seconds,
            name,
            duration_seconds=SEGMENT_SECONDS,
        )
        evidence = {"segment_ids": [segment.id], "message_ids": []}
        add_insight(self._db, self.stream, InsightType.TOPIC, f"{name}\nx", evidence)

    def cheer(self, offset_seconds: int) -> None:
        event = add_event(
            self._db,
            self.stream,
            "channel.cheer",
            offset_seconds=offset_seconds,
            amount=CHEER_BITS,
        )
        event.payload = {"user_login": "baleia", "bits": CHEER_BITS}
        self._db.flush()

    def finance(self, api_client: TestClient) -> dict:
        login_as(api_client, self.channel)
        return api_client.get(f"/api/streams/{self.stream.id}/finance").json()


@pytest.fixture
def live(db: Session) -> TopicLive:
    channel = make_channel(db)
    stream = make_stream(
        db,
        channel,
        started_minutes_ago=LIVE_STARTED_MINUTES_AGO,
        duration_minutes=LIVE_MINUTES,
    )
    return TopicLive(db, channel, stream)


@pytest.fixture
def money_between_topics(live: TopicLive) -> TopicLive:
    live.add_topic("Abertura", OPENING_AT)
    live.add_topic("Deploy", DEPLOY_AT)
    live.cheer(BETWEEN_TOPICS_AT)
    return live


def test_live_finance_credits_money_between_topics_to_the_nearest_one(
    api_client: TestClient, money_between_topics: TopicLive
) -> None:
    assert money_between_topics.finance(api_client)["by_topic"] == [
        {"name": "Deploy", "estimated_usd": CHEER_USD, "events": 1}
    ]


def test_live_finance_moment_names_the_nearest_topic(
    api_client: TestClient, money_between_topics: TopicLive
) -> None:
    moments = money_between_topics.finance(api_client)["top_moments"]
    assert moments[0]["topic"] == "Deploy"


def test_channel_finance_credits_money_between_topics_to_the_nearest_one(
    api_client: TestClient, money_between_topics: TopicLive
) -> None:
    login_as(api_client, money_between_topics.channel)
    finance = api_client.get("/api/channel").json()["finance"]
    assert finance["top_monetizing_topics"] == [
        {"name": "Deploy", "estimated_usd": CHEER_USD, "streams": 1}
    ]


def test_digest_credits_money_between_topics_to_the_nearest_one(
    db: Session, money_between_topics: TopicLive
) -> None:
    started = money_between_topics.stream.started_at
    digest = build_period(
        db,
        money_between_topics.channel,
        DigestPeriod.WEEKLY,
        started - DIGEST_MARGIN,
        started + DIGEST_MARGIN,
    )
    revenue = [(topic.name, topic.estimated_usd) for topic in digest.topic_revenue]
    assert revenue == [("Deploy", CHEER_USD)]


def test_money_inside_two_overlapping_topics_counts_once_for_the_higher_ranked(
    api_client: TestClient, live: TopicLive
) -> None:
    live.add_topic("Deploy", OVERLAP_FIRST_AT)
    live.add_topic("Caddy", OVERLAP_SECOND_AT)
    live.cheer(INSIDE_BOTH_AT)
    assert live.finance(api_client)["by_topic"] == [
        {"name": "Deploy", "estimated_usd": CHEER_USD, "events": 1}
    ]


def test_money_in_a_live_without_topics_is_credited_to_no_topic(
    api_client: TestClient, live: TopicLive
) -> None:
    live.cheer(BETWEEN_TOPICS_AT)
    assert live.finance(api_client)["by_topic"] == []
