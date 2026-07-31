"""Block summarizing must leave the final steps able to run.

Blocks grow with how long the live ran; summary/topics/recommendations do not.
Before the reserve, a long live spent the whole budget on blocks and arrived at
the steps the streamer actually reads with nothing left (measured in prod on
2026-07-28: 6 of 14 streams lost summary+topics+recommendations, 2 of them
ended up with zero insights).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from core.llm import TokenBudget
from core.models import Stream
from workers.analyze.pipeline import (
    BLOCK_MINUTES,
    RECOMMEND_OUTPUT_TOKENS,
    SUMMARY_OUTPUT_TOKENS,
    TOPICS_PROMPT_INPUT_CAP,
    AnalysisStats,
    PromptContext,
    _summarize_blocks,
)


class WordBackend:
    """Tokenizer = whitespace words, like the other budget tests."""

    model_name = "fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        return '{"content": "resumo do bloco"}'


def _long_stream(hours: int) -> Stream:
    started = datetime(2026, 7, 28, 20, 0, tzinfo=UTC)
    return Stream(
        id=1,
        channel_id=1,
        started_at=started,
        ended_at=started + timedelta(hours=hours),
    )


def _budget_after_blocks(monkeypatch, max_input: int, hours: int):
    """Runs block summarizing over a live of `hours` and returns the budget."""
    monkeypatch.setattr(
        "workers.analyze.pipeline._window_context",
        # long enough that fit_input actually saturates BLOCK_PROMPT_INPUT_CAP,
        # which is what makes a real live exhaust the budget
        lambda *a, **k: PromptContext(text="palavra " * 3000, message_ids=set(), segment_ids=set()),
    )
    budget = TokenBudget(WordBackend(), max_input=max_input, max_output=max_input)
    stats = AnalysisStats()
    summaries = _summarize_blocks(Mock(), _long_stream(hours), WordBackend(), budget, stats, "pt")
    return budget, stats, summaries


def test_long_live_still_affords_the_final_steps(monkeypatch) -> None:
    # 6h = 24 blocks, the shape that truncated in production.
    budget, stats, summaries = _budget_after_blocks(monkeypatch, 30000, hours=6)

    assert summaries, "blocks should still be summarized"
    assert stats.skipped_for_budget, "a 6h live cannot fit every block in 30k"
    # the point of the reserve: what the streamer reads still gets to run
    assert budget.can_afford(TOPICS_PROMPT_INPUT_CAP, SUMMARY_OUTPUT_TOKENS)
    assert budget.can_afford(TOPICS_PROMPT_INPUT_CAP, RECOMMEND_OUTPUT_TOKENS)


def test_short_live_skips_nothing(monkeypatch) -> None:
    budget, stats, summaries = _budget_after_blocks(monkeypatch, 90000, hours=1)

    assert len(summaries) == 60 // BLOCK_MINUTES
    assert stats.skipped_for_budget == []
    assert budget.can_afford(TOPICS_PROMPT_INPUT_CAP, SUMMARY_OUTPUT_TOKENS)


def test_reserve_is_what_stops_the_blocks(monkeypatch) -> None:
    """Not just 'some budget left': it stops while the final steps still fit,
    which is the difference from simply running out."""
    budget, stats, _ = _budget_after_blocks(monkeypatch, 30000, hours=12)

    assert stats.skipped_for_budget
    assert budget.input_remaining >= TOPICS_PROMPT_INPUT_CAP
