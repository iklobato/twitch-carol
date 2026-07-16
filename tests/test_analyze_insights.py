from unittest.mock import Mock

import pytest

from core.llm import TokenBudget
from core.models import InsightType, Stream
from workers.analyze import pipeline
from workers.analyze.evidence import validated_evidence
from workers.analyze.pipeline import (
    AnalysisStats,
    PromptContext,
    _call_and_store,
    _parse_json,
)


def test_parse_json_unwraps_markdown_fence() -> None:
    # Anthropic via OpenRouter fences JSON despite response_format=json_object.
    assert _parse_json('```json\n{"content": "oi"}\n```') == {"content": "oi"}
    assert _parse_json('```\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('{"plain": true}') == {"plain": True}
    assert _parse_json("not json at all") is None


class ScriptedBackend:
    model_name = "scripted"

    def __init__(self, response: str) -> None:
        self._response = response

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        return self._response


def _stream() -> Stream:
    return Stream(id=9, channel_id=1)


def _run(
    monkeypatch: pytest.MonkeyPatch, response: str, evidence_result
) -> tuple[Mock, AnalysisStats, str | None]:
    db = Mock()
    stats = AnalysisStats()
    backend = ScriptedBackend(response)
    budget = TokenBudget(backend, 1000, 1000)
    context = PromptContext(text="ctx", message_ids={1}, segment_ids=set())
    monkeypatch.setattr(pipeline, "validated_evidence", lambda *args: evidence_result)
    content = _call_and_store(
        db,
        _stream(),
        backend,
        budget,
        "prompt",
        100,
        InsightType.SUMMARY,
        context,
        stats,
    )
    return db, stats, content


def test_insight_with_verified_evidence_is_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, stats, content = _run(
        monkeypatch,
        '{"content": "Resumo da live.", "message_ids": [1], "segment_ids": []}',
        {"message_ids": [1], "segment_ids": []},
    )
    assert content == "Resumo da live."
    assert stats.insights_stored == 1
    insight = db.add.call_args[0][0]
    assert insight.evidence == {"message_ids": [1], "segment_ids": []}
    assert insight.model_used == "scripted"


def test_insight_without_verifiable_evidence_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, stats, content = _run(
        monkeypatch,
        '{"content": "Resumo inventado.", "message_ids": [999], "segment_ids": []}',
        None,  # validation found nothing real
    )
    assert content is None
    assert stats.insights_stored == 0
    assert stats.insights_discarded == 1
    db.add.assert_not_called()


def test_unparseable_llm_output_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    db, stats, content = _run(monkeypatch, "não sou json", {"message_ids": [1]})
    assert content is None
    assert stats.insights_discarded == 1
    db.add.assert_not_called()


def test_validated_evidence_filters_ids_missing_from_db() -> None:
    db = Mock()
    db.scalars.side_effect = [[7], []]  # messages found in DB: only 7; segments: none
    evidence = validated_evidence(
        db,
        1,
        {"message_ids": [7, 999], "segment_ids": [123]},
        allowed_message_ids={7, 999},
        allowed_segment_ids={123},
    )
    assert evidence == {"message_ids": [7], "segment_ids": []}


def test_validated_evidence_rejects_hallucinated_id_that_exists_in_db() -> None:
    """Id 7 exists in the stream, but the model never saw it in the prompt:
    citing it is hallucination, not evidence."""
    db = Mock()
    evidence = validated_evidence(
        db,
        1,
        {"content": "x", "message_ids": [7], "segment_ids": []},
        allowed_message_ids=set(),
        allowed_segment_ids=set(),
    )
    assert evidence is None
    db.scalars.assert_not_called()


def test_validated_evidence_rejects_all_fake() -> None:
    db = Mock()
    assert (
        validated_evidence(
            db,
            1,
            {"message_ids": [999], "segment_ids": [888]},
            allowed_message_ids={1},
            allowed_segment_ids={2},
        )
        is None
    )
