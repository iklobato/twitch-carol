"""End-to-end analysis over a real database: peaks from SQL, insights stored
with validated evidence, hallucinating models fully rejected."""

import json
import re

import pytest
from sqlalchemy import select

from core.models import Insight, InsightType, Peak, Stream
from tests.factories import add_chat, add_event, add_segment, make_channel, make_stream
from workers.analyze.pipeline import run_analysis

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


class PromptAwareFakeLLM:
    """Extracts the candidate ids offered in the prompt and cites them,
    which is exactly what a well-behaved model should do."""

    model_name = "prompt-aware-fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _candidates(self, prompt: str) -> tuple[list[int], list[int]]:
        segment_ids: list[int] = []
        message_ids: list[int] = []
        section = None
        for line in prompt.splitlines():
            if "TRECHOS DA FALA" in line:
                section = "segments"
                continue
            if "MENSAGENS DO CHAT" in line:
                section = "messages"
                continue
            match = re.match(r"^(\d+): ", line)
            if match is None:
                continue
            if section == "segments":
                segment_ids.append(int(match.group(1)))
            elif section == "messages":
                message_ids.append(int(match.group(1)))
        return segment_ids, message_ids

    def generate(self, prompt: str, max_tokens: int) -> str:
        segment_ids, message_ids = self._candidates(prompt)
        if '"topics"' in prompt:
            topics = [
                {
                    "name": f"Assunto {index + 1}",
                    "description": "Descrição do assunto.",
                    "segment_ids": [segment_id],
                    "message_ids": [],
                }
                for index, segment_id in enumerate(segment_ids[:3])
            ]
            return json.dumps({"topics": topics})
        return json.dumps(
            {
                "content": "Texto gerado com base nas evidências.",
                "segment_ids": segment_ids[:2],
                "message_ids": message_ids[:2],
            }
        )


class HallucinatingFakeLLM(PromptAwareFakeLLM):
    """Cites ids that were never offered: every insight must be discarded."""

    model_name = "hallucinating-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        if '"topics"' in prompt:
            return json.dumps(
                {
                    "topics": [
                        {
                            "name": "Inventado",
                            "segment_ids": [987654],
                            "message_ids": [],
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "content": "Inventei tudo.",
                "segment_ids": [987654],
                "message_ids": [123456],
            }
        )


def _seed_analyzable_stream(db) -> Stream:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=20)
    # calm baseline + strong burst so SQL peak detection fires
    add_chat(
        db, stream, 30, offset_seconds=0, spread_seconds=600, text="papo tranquilo"
    )
    add_chat(db, stream, 120, offset_seconds=600, spread_seconds=60, text="HYPE DEMAIS")
    add_segment(db, stream, 30, "hoje o tema é arquitetura de software")
    add_segment(db, stream, 620, "olha essa surpresa ao vivo, chat explodindo")
    add_segment(db, stream, 900, "fechando a live com o resumo do que vimos")
    add_event(db, stream, "channel.raid", offset_seconds=605, amount=80)
    return stream


def test_run_analysis_stores_validated_insights_and_peaks(db) -> None:
    stream = _seed_analyzable_stream(db)
    stats = run_analysis(db, stream, PromptAwareFakeLLM())
    db.commit()

    peaks = db.scalars(select(Peak).where(Peak.stream_id == stream.id)).all()
    assert len(peaks) >= 1

    insights = db.scalars(select(Insight).where(Insight.stream_id == stream.id)).all()
    types = {i.type for i in insights}
    assert InsightType.SUMMARY in types
    assert InsightType.PEAK_EXPLANATION in types
    assert InsightType.TOPIC in types
    assert stats.insights_discarded == 0

    from core.models import ChatMessage, TranscriptSegment

    message_ids = set(
        db.scalars(select(ChatMessage.id).where(ChatMessage.stream_id == stream.id))
    )
    segment_ids = set(
        db.scalars(
            select(TranscriptSegment.id).where(TranscriptSegment.stream_id == stream.id)
        )
    )
    for insight in insights:
        assert set(insight.evidence.get("message_ids", [])) <= message_ids
        assert set(insight.evidence.get("segment_ids", [])) <= segment_ids
        assert insight.evidence.get("message_ids") or insight.evidence.get(
            "segment_ids"
        )

    topics = [i for i in insights if i.type == InsightType.TOPIC]
    assert [t.evidence["rank"] for t in topics] == list(range(1, len(topics) + 1))
    assert insights[0].model_used == "prompt-aware-fake"
    assert all(i.tokens_in > 0 for i in insights)


def test_run_analysis_rejects_every_hallucinated_insight(db) -> None:
    stream = _seed_analyzable_stream(db)
    stats = run_analysis(db, stream, HallucinatingFakeLLM())
    db.commit()

    insights = db.scalars(select(Insight).where(Insight.stream_id == stream.id)).all()
    assert insights == []
    assert stats.insights_stored == 0
    assert stats.insights_discarded >= 2  # peak + summary + topics all rejected


def test_run_analysis_is_idempotent_on_rerun(db) -> None:
    stream = _seed_analyzable_stream(db)
    run_analysis(db, stream, PromptAwareFakeLLM())
    db.commit()
    first_count = len(
        db.scalars(select(Insight).where(Insight.stream_id == stream.id)).all()
    )

    run_analysis(db, stream, PromptAwareFakeLLM())
    db.commit()
    second_count = len(
        db.scalars(select(Insight).where(Insight.stream_id == stream.id)).all()
    )
    assert first_count == second_count

    peaks = db.scalars(select(Peak).where(Peak.stream_id == stream.id)).all()
    assert len({p.id for p in peaks}) == len(peaks)


def test_run_analysis_on_empty_stream_stores_nothing(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    stats = run_analysis(db, stream, PromptAwareFakeLLM())
    db.commit()
    assert stats.insights_stored == 0
    assert db.scalars(select(Peak).where(Peak.stream_id == stream.id)).all() == []
