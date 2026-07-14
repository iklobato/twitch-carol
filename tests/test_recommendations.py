"""LLM recommendations grounded in SQL facts (peaks, dips, retention).
Each recommendation must cite a real speech segment from the facts."""

import json

import pytest
from sqlalchemy import select

from core.llm import TokenBudget
from core.models import Insight, InsightType, Stream, TranscriptSegment
from tests.factories import (
    add_chat,
    add_segment,
    add_viewer_samples,
    make_channel,
    make_stream,
)
from workers.analyze.peaks import compute_and_store_peaks
from workers.analyze.pipeline import AnalysisStats, _recommend

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


class GroundedFakeLLM:
    """Cites the fact numbers offered in the FATOS prompt, like a good model."""

    model_name = "grounded-fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def _fact_numbers(self, prompt: str) -> list[int]:
        import re

        return [int(m) for m in re.findall(r"\[(\d+)\]", prompt)]

    def generate(self, prompt: str, max_tokens: int) -> str:
        numbers = self._fact_numbers(prompt)
        return json.dumps(
            {
                "recommendations": [
                    {
                        "content": "Faça mais momentos de raid, o chat adorou.",
                        "fact_ids": numbers[:1],
                    },
                    {
                        "content": "Evite ler termos longos ao vivo.",
                        "fact_ids": numbers[-1:],
                    },
                ]
            }
        )


class UngroundedFakeLLM(GroundedFakeLLM):
    model_name = "ungrounded-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {"recommendations": [{"content": "Inventei isso.", "fact_ids": [999]}]}
        )


def _seed_stream_with_facts(db) -> Stream:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=20)
    # a chat burst around 300s -> a peak
    add_chat(
        db, stream, 20, offset_seconds=0, spread_seconds=1200, text="conversa normal"
    )
    add_chat(db, stream, 120, offset_seconds=300, spread_seconds=60, text="RAID HYPE")
    # a wide speech segment covering both the peak window and the dip below,
    # so the SQL facts anchor to a real segment id (bucket alignment aside)
    add_segment(
        db, stream, 240, "chegou uma raid enorme, bem-vindos", duration_seconds=240
    )
    # viewers climb to 140 then crash to 40 at minute 4 (240s), inside the speech
    add_viewer_samples(db, stream, [50, 80, 120, 130, 140, 40, 45, 50])
    compute_and_store_peaks(db, stream)
    db.flush()
    return stream


def test_recommendations_are_stored_and_grounded(db) -> None:

    stream = _seed_stream_with_facts(db)
    backend = GroundedFakeLLM()
    stats = AnalysisStats()
    _recommend(db, stream, backend, TokenBudget(backend, 30000, 3000), stats)
    db.flush()

    recs = db.scalars(
        select(Insight)
        .where(Insight.stream_id == stream.id)
        .where(Insight.type == InsightType.RECOMMENDATION)
        .order_by(Insight.id)
    ).all()
    assert len(recs) == 2
    assert recs[0].content.startswith("Faça mais")
    assert recs[0].evidence["rank"] == 1
    valid_segments = set(
        db.scalars(
            select(TranscriptSegment.id).where(TranscriptSegment.stream_id == stream.id)
        )
    )
    for rec in recs:
        assert set(rec.evidence["segment_ids"]) <= valid_segments
        assert rec.evidence["segment_ids"]


def test_ungrounded_recommendations_are_discarded(db) -> None:

    stream = _seed_stream_with_facts(db)
    backend = UngroundedFakeLLM()
    stats = AnalysisStats()
    _recommend(db, stream, backend, TokenBudget(backend, 30000, 3000), stats)
    db.flush()

    recs = db.scalars(
        select(Insight)
        .where(Insight.stream_id == stream.id)
        .where(Insight.type == InsightType.RECOMMENDATION)
    ).all()
    assert recs == []
    assert stats.insights_discarded >= 1


def test_no_recommendations_without_facts(db) -> None:

    channel = make_channel(db)
    stream = make_stream(db, channel)  # no viewers, no peaks, no speech
    backend = GroundedFakeLLM()
    stats = AnalysisStats()
    _recommend(db, stream, backend, TokenBudget(backend, 30000, 3000), stats)
    db.flush()
    assert stats.insights_stored == 0
