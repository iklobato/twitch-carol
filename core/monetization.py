"""Account-level monetization recommendations. The LLM only phrases advice
around numbered SQL facts and must cite the fact numbers that back each one, so
nothing is invented (same grounding rule as the per-stream recommendations)."""

import json
import logging
from collections import defaultdict

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.finance import MONEY_EVENT_TYPES, event_contributor, event_usd
from core.llm import LLMBackend, TokenBudget
from core.models import (
    ChannelRecommendation,
    ChatMessage,
    Event,
    Stream,
    Subscription,
    ViewerSample,
)

logger = logging.getLogger(__name__)

RECOMMEND_MAX = 6
RECOMMEND_INPUT_CAP = 4000
RECOMMEND_OUTPUT_TOKENS = 1500
SECONDS_PER_HOUR = 3600
HYPE_TRAIN_END = "channel.hype_train.end"
REDEMPTION_ADD = "channel.channel_points_custom_reward_redemption.add"
SUB_END = "channel.subscription.end"


def build_monetization_facts(
    db: Session, channel_id: int, ready_ids: list[int]
) -> list[str]:
    """Numbered, SQL-derived monetization facts. Only facts backed by real data
    are included, so the LLM can only ground advice in what actually happened."""
    facts: list[str] = []

    def add(text: str) -> None:
        facts.append(f"[{len(facts) + 1}] {text}")

    money = db.scalars(
        select(Event).where(
            Event.channel_id == channel_id, Event.type.in_(MONEY_EVENT_TYPES)
        )
    ).all()
    total = sum(event_usd(e) for e in money)
    per_login: dict[str, float] = defaultdict(float)
    per_stream: dict[int, float] = defaultdict(float)
    for event in money:
        per_stream[event.stream_id] += event_usd(event)
        login = event_contributor(event)
        if login:
            per_login[login] += event_usd(event)
    if total > 0:
        add(f"Receita estimada total: US$ {total:.2f}.")
        if per_login:
            top_login, top_usd = max(per_login.items(), key=lambda item: item[1])
            add(
                f"Seu maior contribuinte ({top_login}) representa "
                f"{round(top_usd / total * 100)}% da receita."
            )

    _add_category_fact(db, ready_ids, per_stream, add)
    _add_engagement_facts(db, ready_ids, add)
    _add_subscriber_facts(db, channel_id, ready_ids, add)
    return facts


def _add_category_fact(db, ready_ids, per_stream, add) -> None:
    if not ready_ids:
        return
    usd: dict[str, float] = defaultdict(float)
    seconds: dict[str, float] = defaultdict(float)
    for stream_id, category, started_at, ended_at in db.execute(
        select(Stream.id, Stream.category, Stream.started_at, Stream.ended_at).where(
            Stream.id.in_(ready_ids)
        )
    ):
        if not category:
            continue
        usd[category] += per_stream.get(stream_id, 0.0)
        if ended_at is not None:
            seconds[category] += (ended_at - started_at).total_seconds()
    per_hour = {
        cat: usd[cat] / (seconds[cat] / SECONDS_PER_HOUR)
        for cat in usd
        if seconds.get(cat, 0) > 0 and usd[cat] > 0
    }
    if per_hour:
        best = max(per_hour.items(), key=lambda item: item[1])
        add(f"A categoria '{best[0]}' rende US$ {best[1]:.2f} por hora transmitida.")


def _add_engagement_facts(db, ready_ids, add) -> None:
    if not ready_ids:
        return
    events = db.scalars(
        select(Event)
        .where(Event.stream_id.in_(ready_ids))
        .where(Event.type.in_([HYPE_TRAIN_END, REDEMPTION_ADD]))
    ).all()
    hype = [e for e in events if e.type == HYPE_TRAIN_END]
    if hype:
        best_level = max(int((e.payload or {}).get("level", 0)) for e in hype)
        add(f"Você teve {len(hype)} hype train(s), melhor nível {best_level}.")
    reward_counts: dict[str, int] = defaultdict(int)
    for event in events:
        if event.type != REDEMPTION_ADD:
            continue
        title = ((event.payload or {}).get("reward") or {}).get("title")
        if title:
            reward_counts[title] += 1
    if reward_counts:
        top = max(reward_counts.items(), key=lambda item: item[1])
        add(f"A recompensa de pontos mais resgatada é '{top[0]}' ({top[1]} vezes).")


def _add_subscriber_facts(db, channel_id, ready_ids, add) -> None:
    tier_rows = db.execute(
        select(Subscription.tier, func.count())
        .where(Subscription.channel_id == channel_id)
        .group_by(Subscription.tier)
    ).all()
    total_subs = sum(count for _, count in tier_rows)
    if total_subs:
        tiers = ", ".join(f"{tier}:{count}" for tier, count in sorted(tier_rows))
        add(f"{total_subs} assinantes ativos (tiers {tiers}).")
    if ready_ids:
        ended = db.scalar(
            select(func.count()).where(
                Event.stream_id.in_(ready_ids), Event.type == SUB_END
            )
        )
        if ended:
            add(f"{int(ended)} assinatura(s) terminaram (churn).")
        pct = _engaged_pct(db, ready_ids)
        if pct is not None:
            add(f"{pct}% dos viewers escrevem no chat (o resto observa).")


def _engaged_pct(db, ready_ids) -> float | None:
    chatters = {
        row[0]: row[1]
        for row in db.execute(
            select(
                ChatMessage.stream_id, func.count(func.distinct(ChatMessage.author_id))
            )
            .where(ChatMessage.stream_id.in_(ready_ids))
            .group_by(ChatMessage.stream_id)
        )
    }
    peaks = {
        row[0]: row[1]
        for row in db.execute(
            select(ViewerSample.stream_id, func.max(ViewerSample.viewer_count))
            .where(ViewerSample.stream_id.in_(ready_ids))
            .group_by(ViewerSample.stream_id)
        )
    }
    ratios = [
        chatters.get(sid, 0) / peaks[sid] for sid in ready_ids if peaks.get(sid, 0) > 0
    ]
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios) * 100, 1)


def _parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def generate_channel_recommendations(
    db: Session,
    channel_id: int,
    facts: list[str],
    backend: LLMBackend,
    budget: TokenBudget,
) -> int:
    """Replace the channel's recommendation set. `facts` are pre-built numbered
    strings (e.g. "[1] ..."). Returns how many grounded recommendations stored."""
    if not facts:
        return 0
    if not budget.can_afford(
        backend.count_tokens("\n".join(facts)), RECOMMEND_OUTPUT_TOKENS
    ):
        return 0

    prompt = (
        "FATOS de monetização medidos do canal na Twitch (cada um com um número "
        "entre colchetes):\n"
        + "\n".join(facts)
        + "\nCom base SOMENTE nesses fatos, dê recomendações práticas para o "
        "streamer ganhar mais dinheiro (faça mais do que rende, corte o que não "
        'converte). Responda APENAS um JSON válido: {"recommendations": '
        '[{"content": "<recomendação em 1-2 frases, português do Brasil>", '
        '"fact_ids": [números dos fatos que embasam]}]}. Cite pelo menos um número '
        f"de fato por recomendação, máximo {RECOMMEND_MAX}, seja concreto."
    )
    response = backend.generate(prompt, RECOMMEND_OUTPUT_TOKENS)
    budget.spend(prompt, response)
    parsed = _parse_json(response)
    recommendations = parsed.get("recommendations") if parsed else None
    if not isinstance(recommendations, list):
        logger.warning(
            "channel recommendations discarded: unparseable",
            extra={"channel_id": channel_id},
        )
        return 0

    fact_text = {index + 1: fact for index, fact in enumerate(facts)}
    db.execute(
        delete(ChannelRecommendation).where(
            ChannelRecommendation.channel_id == channel_id
        )
    )
    stored = 0
    for item in recommendations[:RECOMMEND_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        raw_facts = item.get("fact_ids", [])
        cited = (
            [fact_text[n] for n in raw_facts if isinstance(n, int) and n in fact_text]
            if isinstance(raw_facts, list)
            else []
        )
        if not content or not cited:
            logger.warning(
                "channel recommendation discarded: no grounded fact cited",
                extra={"channel_id": channel_id},
            )
            continue
        db.add(
            ChannelRecommendation(
                channel_id=channel_id,
                content=content,
                evidence={"facts": cited},
                model_used=backend.model_name,
            )
        )
        stored += 1
    return stored
