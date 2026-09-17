"""LLM insights for the email digest, grounded in numbered facts built from
the Digest that was already computed (no DB access of their own)."""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from core.digest import build_period
from core.digest_insights import build_digest_facts, generate_digest_insights
from core.llm import TokenBudget
from core.models import DigestPeriod, InsightType
from tests.factories import (
    add_event,
    add_insight,
    add_segment,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

WEEK_START = datetime.now(UTC) - timedelta(days=10)
WEEK_END = WEEK_START + timedelta(days=7)


class GroundedFakeLLM:
    model_name = "grounded-fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        numbers = [int(m) for m in re.findall(r"\[(\d+)\]", prompt)]
        return json.dumps(
            {
                "insights": [
                    {
                        "content": "Deploy foi o assunto que mais rendeu.",
                        "fact_ids": numbers[:1],
                    }
                ]
            }
        )


class UngroundedFakeLLM(GroundedFakeLLM):
    model_name = "ungrounded-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {"insights": [{"content": "Inventei isso.", "fact_ids": [999]}]}
        )


def _digest_with_topic_revenue(db):
    channel = make_channel(db)
    live = make_stream(db, channel, started_minutes_ago=9 * 24 * 60)
    add_event(db, live, "channel.cheer", offset_seconds=310, amount=500, login="baleia")
    segment = add_segment(db, live, 300, "falando de deploy", duration_seconds=60)
    add_insight(
        db,
        live,
        insight_type=InsightType.TOPIC,
        content="Deploy\nx",
        evidence={"segment_ids": [segment.id]},
    )
    return build_period(db, channel, DigestPeriod.WEEKLY, WEEK_START, WEEK_END)


def test_build_digest_facts_cites_the_top_monetizing_topic(db) -> None:
    digest = _digest_with_topic_revenue(db)

    facts = build_digest_facts(digest)

    assert any("Deploy" in fact for fact in facts)


def test_build_digest_facts_is_empty_for_an_empty_digest(db) -> None:
    channel = make_channel(db)
    digest = build_period(db, channel, DigestPeriod.WEEKLY, WEEK_START, WEEK_END)

    assert build_digest_facts(digest) == []


def test_generate_digest_insights_keeps_grounded_takeaways(db) -> None:
    digest = _digest_with_topic_revenue(db)
    facts = build_digest_facts(digest)
    backend = GroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)

    insights = generate_digest_insights(digest, facts, backend, budget)

    assert insights == ["Deploy foi o assunto que mais rendeu."]


def test_generate_digest_insights_discards_an_ungrounded_takeaway(db) -> None:
    digest = _digest_with_topic_revenue(db)
    facts = build_digest_facts(digest)
    backend = UngroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)

    insights = generate_digest_insights(digest, facts, backend, budget)

    assert insights == []  # cited fact 999 does not exist


def test_generate_digest_insights_skips_the_call_with_no_facts(db) -> None:
    backend = GroundedFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)
    digest = _digest_with_topic_revenue(db)

    insights = generate_digest_insights(digest, [], backend, budget)

    assert insights == []
    assert budget.input_spent == 0  # the call never happened
