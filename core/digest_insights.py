"""LLM insights for the weekly/monthly email digest. The model can only
phrase a takeaway around facts already computed in the Digest, and must cite
which one backs it, so nothing in the email is invented (same grounding rule
as core.monetization).

Nothing here touches the database: the facts are built straight from the
already-built Digest (never re-queried), and the result is attached to it
in-memory via core.digest.with_insights, not stored as its own row.
"""

import logging

from core.digest import Digest
from core.i18n import language_name
from core.llm import LLMBackend, TokenBudget, parse_json_object
from core.records import RecordMetric, metric_label

logger = logging.getLogger(__name__)

INSIGHTS_MAX = 4
INSIGHTS_OUTPUT_TOKENS = 600
# How many of the ranked topic/category buckets are worth grounding an
# insight in; the rest are already visible in their own email section.
TOP_BUCKETS = 3


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

    return facts


def generate_digest_insights(
    digest: Digest, facts: list[str], backend: LLMBackend, budget: TokenBudget
) -> list[str]:
    """2-4 short, cited takeaways in the channel's language. Empty (not an
    error) when there is nothing to ground an insight in, or the budget can't
    afford the call: the digest still sends without an insights section."""
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
        "the streamer about what earned money and what changed. Reply with "
        'valid JSON ONLY: {"insights": [{"content": "<takeaway in 1 sentence, '
        f'written in {language_name(digest.language)}>", '
        '"fact_ids": [numbers of the facts behind it]}]}. Cite at least one '
        f"fact number per insight, at most {INSIGHTS_MAX}, be concrete and specific."
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
    insights: list[str] = []
    for item in items[:INSIGHTS_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        raw_facts = item.get("fact_ids", [])
        cited = (
            [n for n in raw_facts if isinstance(n, int) and n in known_fact_ids]
            if isinstance(raw_facts, list)
            else []
        )
        if not content or not cited:
            logger.warning(
                "digest insight discarded: no grounded fact cited",
                extra={"login": digest.login},
            )
            continue
        insights.append(content)
    return insights
