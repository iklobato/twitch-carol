from unittest.mock import Mock

import pytest

from core.llm import TokenBudget
from core.models import InsightType, Stream
from workers.analyze import pipeline
from workers.analyze.pipeline import AnalysisStats, PromptContext, _store_topics


class CountingBackend:
    model_name = "fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        return "{}"


def _run_store(monkeypatch: pytest.MonkeyPatch, topics: list, evidence_results: list):
    db = Mock()
    stats = AnalysisStats()
    backend = CountingBackend()
    results = iter(evidence_results)
    monkeypatch.setattr(pipeline, "validated_evidence", lambda *args: next(results))
    _store_topics(
        db,
        Stream(id=1, channel_id=1),
        backend,
        TokenBudget(backend, 100, 100),
        topics,
        PromptContext(text="", message_ids=set(), segment_ids={10, 11}),
        stats,
    )
    return db, stats


def test_topics_stored_one_insight_per_topic_with_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topics = [
        {"name": "pylight", "description": "framework do projeto", "segment_ids": [10]},
        {
            "name": "bug de autenticação",
            "description": "correção ao vivo",
            "segment_ids": [11],
        },
    ]
    db, stats = _run_store(
        monkeypatch,
        topics,
        [
            {"segment_ids": [10], "message_ids": []},
            {"segment_ids": [11], "message_ids": []},
        ],
    )
    assert stats.insights_stored == 2
    first = db.add.call_args_list[0][0][0]
    second = db.add.call_args_list[1][0][0]
    assert first.type == InsightType.TOPIC
    assert first.content.splitlines()[0] == "pylight"
    assert first.evidence["rank"] == 1
    assert second.evidence["rank"] == 2


def test_topic_without_evidence_is_discarded_and_rank_skips_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topics = [
        {"name": "inventado", "segment_ids": [999]},
        {"name": "real", "segment_ids": [10]},
    ]
    db, stats = _run_store(
        monkeypatch, topics, [None, {"segment_ids": [10], "message_ids": []}]
    )
    assert stats.insights_discarded == 1
    assert stats.insights_stored == 1
    stored = db.add.call_args_list[0][0][0]
    assert stored.content.splitlines()[0] == "real"
    assert stored.evidence["rank"] == 1


def test_malformed_topic_entries_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    db, stats = _run_store(
        monkeypatch, ["texto solto", {"description": "sem nome"}], []
    )
    assert stats.insights_stored == 0
    db.add.assert_not_called()


def test_chat_dump_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # a "name" that is really a dump of chat messages, not a label
    dump = (
        "Streamer joga muito, viewer_05 e viewer_39. qual teclado voce usa? viewer_16"
    )
    db, stats = _run_store(monkeypatch, [{"name": dump, "segment_ids": [10]}], [])
    assert stats.insights_stored == 0
    db.add.assert_not_called()


def test_duplicate_topic_names_collapse(monkeypatch: pytest.MonkeyPatch) -> None:
    topics = [
        {"name": "Subindo API em Produção", "segment_ids": [10]},
        {"name": "Subindo API produção agora", "segment_ids": [11]},  # same subject
    ]
    # only the first reaches evidence validation; the second is deduped before it
    db, stats = _run_store(
        monkeypatch, topics, [{"segment_ids": [10], "message_ids": []}]
    )
    assert stats.insights_stored == 1
    stored = db.add.call_args_list[0][0][0]
    assert stored.content.splitlines()[0] == "Subindo API em Produção"
