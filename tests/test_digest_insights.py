"""LLM insights for the email digest, grounded in numbered facts built from
the Digest that was already computed (no DB access of their own)."""

import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.digest import (
    Digest,
    DigestInsight,
    DigestLive,
    DigestSentiment,
    DigestTopPayer,
    DigestTotals,
    build_period,
)
from core.digest_insights import build_digest_facts, generate_digest_insights
from core.llm import TokenBudget
from core.models import DigestPeriod, InsightType
from core.records import RecordMetric
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
                        "category": "keep",
                        "fact_ids": numbers[:1],
                    }
                ]
            }
        )


class UngroundedFakeLLM(GroundedFakeLLM):
    model_name = "ungrounded-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        return json.dumps(
            {
                "insights": [
                    {"content": "Inventei isso.", "category": "keep", "fact_ids": [999]}
                ]
            }
        )


class BadCategoryFakeLLM(GroundedFakeLLM):
    model_name = "bad-category-fake"

    def generate(self, prompt: str, max_tokens: int) -> str:
        numbers = [int(m) for m in re.findall(r"\[(\d+)\]", prompt)]
        return json.dumps(
            {
                "insights": [
                    {"content": "x", "category": "nonsense", "fact_ids": numbers[:1]}
                ]
            }
        )


_EMPTY_DIGEST = Digest(
    period=DigestPeriod.WEEKLY,
    login="streamer",
    display_name="Streamer",
    start=WEEK_START,
    end=WEEK_END,
    lives=(),
    totals=DigestTotals(metrics={}, unique_chatters=0),
    previous=None,
    moments=(),
    topics=(),
    records=(),
    clips=(),
    topic_revenue=(),
    content_revenue=(),
    top_lives_by_revenue=(),
    top_lives_by_messages=(),
    sentiment=None,
    engaged_users=(),
    top_payers=(),
    money_moments=(),
    daily_revenue={},
    subscriber_churn=None,
    top_reward=None,
    previous_sentiment=None,
    language="en",
)


def _base_digest(**overrides: Any) -> Digest:
    """The empty Digest above, with only the fields a test's fact needs
    overridden, isolating each fact's gate from every other one."""
    return dataclasses.replace(_EMPTY_DIGEST, **overrides)


def _live(
    category: str | None,
    revenue: float = 0.0,
    duration_minutes: float = 60.0,
    chatters: float = 0.0,
    peak_viewers: float = 0.0,
    time_of_day: str = "period.evening",
    stream_id: int = 1,
) -> DigestLive:
    return DigestLive(
        stream_id=stream_id,
        title=None,
        category=category,
        started_at=WEEK_START,
        metrics={
            RecordMetric.REVENUE_USD: revenue,
            RecordMetric.DURATION_MINUTES: duration_minutes,
            RecordMetric.CHATTERS: chatters,
            RecordMetric.PEAK_VIEWERS: peak_viewers,
        },
        time_of_day=time_of_day,
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

    assert insights == [
        DigestInsight(content="Deploy foi o assunto que mais rendeu.", category="keep")
    ]


def test_generate_digest_insights_discards_an_invalid_category(db) -> None:
    digest = _digest_with_topic_revenue(db)
    facts = build_digest_facts(digest)
    backend = BadCategoryFakeLLM()
    budget = TokenBudget(backend, 4000, 1500)

    insights = generate_digest_insights(digest, facts, backend, budget)

    assert insights == []


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


def test_whale_risk_fact_flags_revenue_concentration() -> None:
    digest = _base_digest(
        totals=DigestTotals(
            metrics={RecordMetric.REVENUE_USD: 20.0}, unique_chatters=1
        ),
        top_payers=(DigestTopPayer(login="baleia", estimated_usd=20.0),),
    )

    facts = build_digest_facts(digest)

    assert any("baleia" in fact and "100%" in fact for fact in facts)


def test_whale_risk_fact_absent_below_the_share_threshold() -> None:
    digest = _base_digest(
        totals=DigestTotals(
            metrics={RecordMetric.REVENUE_USD: 100.0}, unique_chatters=2
        ),
        top_payers=(
            DigestTopPayer(login="baleia", estimated_usd=20.0),
        ),  # 20%, gate is 40%
    )

    assert build_digest_facts(digest) == []


def test_category_efficiency_fact_flags_the_best_paying_category() -> None:
    digest = _base_digest(
        lives=(
            _live("Just Chatting", revenue=30.0, duration_minutes=60, stream_id=1),
            _live("Minecraft", revenue=2.0, duration_minutes=60, stream_id=2),
        )
    )

    facts = build_digest_facts(digest)

    assert any("Just Chatting" in fact and "/hour" in fact for fact in facts)


def test_category_efficiency_fact_absent_with_only_one_category() -> None:
    digest = _base_digest(
        lives=(_live("Just Chatting", revenue=30.0, duration_minutes=60, stream_id=1),)
    )

    assert build_digest_facts(digest) == []


def test_best_period_fact_flags_the_best_paying_time_of_day() -> None:
    digest = _base_digest(
        lives=(
            _live(
                "Just Chatting",
                revenue=30.0,
                duration_minutes=60,
                time_of_day="period.evening",
                stream_id=1,
            ),
            _live(
                "Just Chatting",
                revenue=2.0,
                duration_minutes=60,
                time_of_day="period.morning",
                stream_id=2,
            ),
        )
    )

    facts = build_digest_facts(digest)

    assert any("evening" in fact and "morning" in fact for fact in facts)


def test_best_period_fact_absent_with_only_one_time_bucket() -> None:
    digest = _base_digest(
        lives=(
            _live(
                "Just Chatting",
                revenue=30.0,
                duration_minutes=60,
                time_of_day="period.evening",
                stream_id=1,
            ),
        )
    )

    assert build_digest_facts(digest) == []


def test_category_engagement_fact_flags_the_most_participative_category() -> None:
    digest = _base_digest(
        lives=(
            _live("Just Chatting", chatters=45.0, peak_viewers=100.0, stream_id=1),
            _live("Minecraft", chatters=12.0, peak_viewers=100.0, stream_id=2),
        )
    )

    facts = build_digest_facts(digest)

    assert any(
        "Just Chatting" in fact and "0.45 unique chatters per peak viewer" in fact
        for fact in facts
    )


def test_category_engagement_fact_stays_readable_above_one_chatter_per_viewer() -> None:
    """Unique chatters over a whole broadcast can outnumber the single-instant
    peak, so the fact is a ratio per peak viewer, never a share of the audience
    that would read as "136% of the audience chatted"."""
    digest = _base_digest(
        lives=(
            _live("Just Chatting", chatters=136.0, peak_viewers=100.0, stream_id=1),
            _live("Minecraft", chatters=20.0, peak_viewers=100.0, stream_id=2),
        )
    )

    facts = build_digest_facts(digest)

    assert any("1.36 unique chatters per peak viewer" in fact for fact in facts)
    assert not any("%" in fact and "chatt" in fact for fact in facts)


def test_category_engagement_fact_absent_with_only_one_category() -> None:
    digest = _base_digest(
        lives=(_live("Just Chatting", chatters=45.0, peak_viewers=100.0, stream_id=1),)
    )

    assert build_digest_facts(digest) == []


def test_sentiment_trend_fact_compares_against_the_previous_period() -> None:
    digest = _base_digest(
        sentiment=DigestSentiment(label="positive", score=0.42, messages=100),
        previous_sentiment=DigestSentiment(label="negative", score=-0.3, messages=80),
    )

    facts = build_digest_facts(digest)

    assert any("positive" in fact and "negative" in fact for fact in facts)


def test_sentiment_trend_fact_absent_without_a_previous_period_score() -> None:
    digest = _base_digest(
        sentiment=DigestSentiment(label="positive", score=0.42, messages=100)
    )

    assert build_digest_facts(digest) == []


def test_subscriber_churn_fact_states_gained_and_lost() -> None:
    digest = _base_digest(subscriber_churn=(12, 9))

    facts = build_digest_facts(digest)

    assert any("12" in fact and "9" in fact for fact in facts)


def test_subscriber_churn_fact_absent_when_digest_has_none() -> None:
    digest = _base_digest(subscriber_churn=None)

    assert build_digest_facts(digest) == []


def test_top_reward_fact_names_the_most_redeemed_reward() -> None:
    digest = _base_digest(top_reward=("Hydrate", 34))

    facts = build_digest_facts(digest)

    assert any("Hydrate" in fact and "34" in fact for fact in facts)


def test_top_reward_fact_absent_when_digest_has_none() -> None:
    digest = _base_digest(top_reward=None)

    assert build_digest_facts(digest) == []
