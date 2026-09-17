"""LLM insights for the weekly/monthly email digest. The model can only
phrase a takeaway around facts already computed in the Digest, and must cite
which one backs it, so nothing in the email is invented (same grounding rule
as core.monetization).

Nothing here touches the database: the facts are built straight from the
already-built Digest (never re-queried), and the result is attached to it
in-memory via core.digest.with_insights, not stored as its own row.
"""

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable

from core.digest import Digest, DigestInsight, DigestLive
from core.i18n import language_name
from core.llm import LLMBackend, TokenBudget, parse_json_object
from core.monetization import (
    CATEGORY_LIFT_MIN,
    ENGAGEMENT_LIFT_MIN,
    PERIOD_LIFT_MIN,
    WHALE_SHARE_MIN,
)
from core.records import RecordMetric, metric_label

logger = logging.getLogger(__name__)

INSIGHTS_MAX = 8
INSIGHTS_OUTPUT_TOKENS = 900
# How many of the ranked topic/category buckets are worth grounding an
# insight in; the rest are already visible in their own email section.
TOP_BUCKETS = 3
_VALID_CATEGORIES = frozenset({"keep", "stop", "improve"})


def build_digest_facts(digest: Digest) -> list[str]:
    """Numbered, COMPARATIVE facts already computed for the digest. A bare
    total is excluded on purpose (see core.monetization): alone it can only
    produce a tautological insight ("revenue was $X because $X was earned")."""
    facts: list[str] = []

    def add(text: str) -> None:
        facts.append(f"[{len(facts) + 1}] {text}")

    revenue = digest.totals.metrics.get(RecordMetric.REVENUE_USD, 0.0)
    previous_revenue = (
        digest.previous.metrics.get(RecordMetric.REVENUE_USD, 0.0)
        if digest.previous
        else None
    )
    if previous_revenue is not None and previous_revenue > 0:
        delta = round((revenue - previous_revenue) / previous_revenue * 100, 1)
        add(
            f"Estimated revenue this period: US$ {revenue:.2f}, vs US$ "
            f"{previous_revenue:.2f} last period ({delta:+.1f}%)."
        )

    for topic in digest.topic_revenue[:TOP_BUCKETS]:
        add(
            f"The topic '{topic.name}' was on stream during US$ "
            f"{topic.estimated_usd:.2f} of money events, across {topic.streams} "
            "live(s)."
        )

    for bucket in digest.content_revenue[:TOP_BUCKETS]:
        add(
            f"The category '{bucket.category}' earned US$ {bucket.estimated_usd:.2f} "
            f"(US$ {bucket.usd_per_hour:.2f}/hour)."
        )

    if digest.records:
        labels = ", ".join(metric_label(metric, "en") for metric, _ in digest.records)
        add(f"Records broken this period: {labels}.")

    _add_whale_risk_fact(digest, add)
    _add_category_efficiency_fact(digest, add)
    _add_best_period_fact(digest, add)
    _add_category_engagement_fact(digest, add)
    _add_sentiment_trend_fact(digest, add)
    _add_subscriber_churn_fact(digest, add)
    _add_top_reward_fact(digest, add)

    return facts


def _rate_by_bucket(
    lives: Iterable[DigestLive], bucket_of: Callable[[DigestLive], str | None]
) -> dict[str, float]:
    """USD earned per hour of live time, grouped by bucket_of(live). Only
    buckets where both revenue and duration were measured are counted."""
    revenue: dict[str, float] = defaultdict(float)
    minutes: dict[str, float] = defaultdict(float)
    for live in lives:
        bucket = bucket_of(live)
        if bucket is None:
            continue
        revenue[bucket] += live.metrics.get(RecordMetric.REVENUE_USD, 0.0)
        minutes[bucket] += live.metrics.get(RecordMetric.DURATION_MINUTES, 0.0)
    return {
        bucket: revenue[bucket] / (minutes[bucket] / 60)
        for bucket in minutes
        if minutes[bucket] > 0 and revenue[bucket] > 0
    }


def _add_whale_risk_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """One contributor carrying most of the period's revenue: Twitch never
    frames a leaderboard entry as a dependency risk."""
    revenue = digest.totals.metrics.get(RecordMetric.REVENUE_USD, 0.0)
    if revenue <= 0 or not digest.top_payers:
        return
    top = digest.top_payers[0]
    share = top.estimated_usd / revenue
    if share >= WHALE_SHARE_MIN:
        add(
            f"The single biggest contributor ({top.login}) accounts for "
            f"{share * 100:.0f}% of this period's revenue."
        )


def _add_category_efficiency_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """The category that pays best PER HOUR this period versus the period's
    own average. Needs 2+ paying categories to compare."""
    rates = _rate_by_bucket(digest.lives, lambda live: live.category)
    if len(rates) < 2:
        return
    total_revenue = sum(
        live.metrics.get(RecordMetric.REVENUE_USD, 0.0) for live in digest.lives
    )
    total_minutes = sum(
        live.metrics.get(RecordMetric.DURATION_MINUTES, 0.0) for live in digest.lives
    )
    if total_minutes <= 0:
        return
    average = total_revenue / (total_minutes / 60)
    best, rate = max(rates.items(), key=lambda item: item[1])
    if average > 0 and rate >= average * CATEGORY_LIFT_MIN:
        add(
            f"The category '{best}' earned US$ {rate:.2f}/hour this period, "
            f"{rate / average:.1f}x the period's average of US$ {average:.2f}/hour."
        )


def _add_best_period_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """Time-of-day slot (morning/afternoon/evening, channel's own timezone)
    that paid best per hour this period. Needs 2+ populated slots."""
    rates = _rate_by_bucket(digest.lives, lambda live: live.time_of_day)
    if len(rates) < 2:
        return
    best, best_rate = max(rates.items(), key=lambda item: item[1])
    worst, worst_rate = min(rates.items(), key=lambda item: item[1])
    if worst_rate > 0 and best_rate >= worst_rate * PERIOD_LIFT_MIN:
        add(
            f"Lives started in the {best.rsplit('.', 1)[-1]} earned US$ "
            f"{best_rate:.2f}/hour this period, {best_rate / worst_rate:.1f}x the "
            f"ones started in the {worst.rsplit('.', 1)[-1]} (US$ "
            f"{worst_rate:.2f}/hour)."
        )


def _add_category_engagement_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """Category whose audience talks the most (chatters / peak viewers) this
    period: Twitch shows raw viewer counts, never a participation ratio.
    Needs 2+ categories with viewers to compare."""
    ratios: dict[str, list[float]] = defaultdict(list)
    for live in digest.lives:
        if not live.category:
            continue
        peak = live.metrics.get(RecordMetric.PEAK_VIEWERS, 0.0)
        if peak > 0:
            ratios[live.category].append(
                live.metrics.get(RecordMetric.CHATTERS, 0.0) / peak
            )
    per_category = {cat: sum(rs) / len(rs) for cat, rs in ratios.items() if rs}
    if len(per_category) < 2:
        return
    best, best_ratio = max(per_category.items(), key=lambda item: item[1])
    worst, worst_ratio = min(per_category.items(), key=lambda item: item[1])
    if worst_ratio > 0 and best_ratio >= worst_ratio * ENGAGEMENT_LIFT_MIN:
        add(
            f"In '{best}' lives, {best_ratio * 100:.0f}% of the peak audience "
            f"chatted this period, {best_ratio / worst_ratio:.1f}x '{worst}' lives "
            f"({worst_ratio * 100:.0f}%)."
        )


def _add_sentiment_trend_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """Average chat mood this period versus last period: Twitch has no
    sentiment analysis at all."""
    if not digest.sentiment or not digest.previous_sentiment:
        return
    add(
        f"Chat mood this period was {digest.sentiment.label} (score "
        f"{digest.sentiment.score:+.2f}), versus {digest.previous_sentiment.label} "
        f"(score {digest.previous_sentiment.score:+.2f}) last period."
    )


def _add_subscriber_churn_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """Subscribers gained versus lost THIS PERIOD: Twitch only shows the
    current total, never the flow behind it."""
    if not digest.subscriber_churn:
        return
    gained, lost = digest.subscriber_churn
    add(
        f"This period you gained {gained} and lost {lost} subscriber(s) "
        f"(net {gained - lost:+d})."
    )


def _add_top_reward_fact(digest: Digest, add: Callable[[str], None]) -> None:
    """The period's most-redeemed channel-points reward. Needs a rival reward
    to beat, so "most redeemed" means something."""
    if not digest.top_reward:
        return
    title, times = digest.top_reward
    add(
        f"The most-redeemed channel-points reward this period was '{title}' "
        f"({times}x), ahead of every other reward."
    )


def generate_digest_insights(
    digest: Digest, facts: list[str], backend: LLMBackend, budget: TokenBudget
) -> list[DigestInsight]:
    """Up to INSIGHTS_MAX cited, categorized takeaways ("keep"/"stop"/
    "improve") in the channel's language. Empty (not an error) when there is
    nothing to ground an insight in, or the budget can't afford the call: the
    digest still sends without an insights section. A weak period may
    legitimately produce fewer than 5; nothing here pads the count."""
    if not facts:
        return []
    if not budget.can_afford(
        backend.count_tokens("\n".join(facts)), INSIGHTS_OUTPUT_TOKENS
    ):
        return []

    # English prompt whatever the channel speaks; only the answer is
    # localized, so there is one prompt to maintain instead of one per language.
    prompt = (
        "FACTS measured from a Twitch channel's weekly/monthly recap (each "
        "numbered in brackets):\n"
        + "\n".join(facts)
        + "\nBased ONLY on these facts, write the most important takeaways for "
        "the streamer: what to KEEP doing (it's working), what to STOP doing "
        "(it's hurting them or wasting time), and what to IMPROVE (a concrete "
        "change with a clear upside). Reply with valid JSON ONLY: "
        '{"insights": [{"content": "<takeaway in 1 sentence, written in '
        f'{language_name(digest.language)}>", "category": "keep"|"stop"|'
        '"improve", "fact_ids": [numbers of the facts behind it]}]}. Cite at '
        f"least one fact number per insight, at most {INSIGHTS_MAX} insights "
        "total, be concrete and specific."
    )
    response = backend.generate(prompt, INSIGHTS_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = parse_json_object(response)
    items = parsed.get("insights") if parsed else None
    if not isinstance(items, list):
        logger.warning(
            "digest insights discarded: unparseable", extra={"login": digest.login}
        )
        return []

    known_fact_ids = set(range(1, len(facts) + 1))
    insights: list[DigestInsight] = []
    for item in items[:INSIGHTS_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        category = str(item.get("category", "")).strip()
        raw_facts = item.get("fact_ids", [])
        cited = (
            [n for n in raw_facts if isinstance(n, int) and n in known_fact_ids]
            if isinstance(raw_facts, list)
            else []
        )
        if not content or not cited or category not in _VALID_CATEGORIES:
            logger.warning(
                "digest insight discarded: no grounded fact cited or bad category",
                extra={"login": digest.login},
            )
            continue
        insights.append(DigestInsight(content=content, category=category))
    return insights
