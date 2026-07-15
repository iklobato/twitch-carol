"""Account-level monetization recommendations. The LLM only phrases advice
around numbered SQL facts and must cite the fact numbers that back each one, so
nothing is invented (same grounding rule as the per-stream recommendations).

Every fact fed to the model is COMPARATIVE: a winner vs the rest, a value above
a risk threshold, or a gain vs a loss. Bare totals (total revenue, active-sub
count) are deliberately excluded here: alone they can only produce tautological
advice ("raise revenue by raising revenue"). Those totals still reach the user
as plain stats via the finance/channel API, not as LLM grounding."""

import json
import logging
from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.finance import MONEY_EVENT_TYPES, SUBSCRIBE, event_contributor, event_usd
from core.llm import LLMBackend, TokenBudget
from core.models import (
    Channel,
    ChannelRecommendation,
    ChatMessage,
    Event,
    Stream,
    ViewerSample,
)

logger = logging.getLogger(__name__)

RECOMMEND_MAX = 6
RECOMMEND_OUTPUT_TOKENS = 1500
SECONDS_PER_HOUR = 3600
SUB_END = "channel.subscription.end"
REDEMPTION_ADD = "channel.channel_points_custom_reward_redemption.add"

# A fact is only worth advising on when the comparison is real: the best option
# must beat the reference by this much, or a share must cross this risk line.
CATEGORY_LIFT_MIN = 1.5
PERIOD_LIFT_MIN = 1.5
ENGAGEMENT_LIFT_MIN = 1.5
WHALE_SHARE_MIN = 0.40


def build_monetization_facts(
    db: Session, channel_id: int, ready_ids: list[int]
) -> list[str]:
    """Numbered, SQL-derived, COMPARATIVE monetization facts. Each helper only
    appends when a genuine comparison exists, so the LLM can never ground advice
    in a bare total."""
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

    streams = _ready_streams(db, ready_ids)
    _add_whale_risk(per_login, total, add)
    _add_category_efficiency(streams, per_stream, add)
    _add_best_period(db, channel_id, streams, per_stream, add)
    _add_subscriber_trend(db, ready_ids, add)
    _add_category_engagement(db, streams, add)
    _add_top_reward(db, ready_ids, add)
    return facts


def _ready_streams(db: Session, ready_ids: list[int]) -> list[Stream]:
    if not ready_ids:
        return []
    return list(db.scalars(select(Stream).where(Stream.id.in_(ready_ids))))


def _add_whale_risk(per_login: dict[str, float], total: float, add) -> None:
    """One contributor carrying most of the revenue is a concentration risk,
    which points at a concrete action (diversify). A share below the line is
    just a stat, so it stays out."""
    if total <= 0 or not per_login:
        return
    login, usd = max(per_login.items(), key=lambda item: item[1])
    share = usd / total
    if share >= WHALE_SHARE_MIN:
        add(
            f"Seu maior contribuinte ({login}) concentra {round(share * 100)}% da "
            "receita: risco de depender de uma pessoa só."
        )


def _hours_by(streams: list[Stream], key) -> tuple[dict, dict]:
    """Sum revenue-proxy seconds and let the caller fill usd; returns
    (seconds_by_key, group_by_key) so callers stay small."""
    seconds: dict = defaultdict(float)
    groups: dict = defaultdict(list)
    for stream in streams:
        if stream.ended_at is None:
            continue
        bucket = key(stream)
        if bucket is None:
            continue
        seconds[bucket] += (stream.ended_at - stream.started_at).total_seconds()
        groups[bucket].append(stream.id)
    return seconds, groups


def _per_hour_rates(seconds: dict, groups: dict, per_stream: dict[int, float]) -> dict:
    rates = {}
    for bucket, ids in groups.items():
        hours = seconds[bucket] / SECONDS_PER_HOUR
        usd = sum(per_stream.get(sid, 0.0) for sid in ids)
        if hours > 0 and usd > 0:
            rates[bucket] = usd / hours
    return rates


def _add_category_efficiency(
    streams: list[Stream], per_stream: dict[int, float], add
) -> None:
    """The category that pays best PER HOUR versus the channel average: tells
    the streamer what to put more of on the schedule. Needs 2+ paying
    categories, else 'versus average' is meaningless."""
    seconds, groups = _hours_by(streams, lambda s: s.category)
    rates = _per_hour_rates(seconds, groups, per_stream)
    if len(rates) < 2:
        return
    total_usd = sum(per_stream.get(sid, 0.0) for ids in groups.values() for sid in ids)
    total_hours = sum(seconds[b] for b in rates) / SECONDS_PER_HOUR
    if total_hours <= 0:
        return
    average = total_usd / total_hours
    best, rate = max(rates.items(), key=lambda item: item[1])
    if average > 0 and rate >= average * CATEGORY_LIFT_MIN:
        add(
            f"A categoria '{best}' rende US$ {rate:.2f}/h, {rate / average:.1f}x a "
            f"média das suas lives (US$ {average:.2f}/h): priorize-a na grade."
        )


_PERIODS = (("manhã", 5, 12), ("tarde", 12, 18))


def _period(hour: int) -> str:
    for name, start, end in _PERIODS:
        if start <= hour < end:
            return name
    return "noite"


def _channel_tz(db: Session, channel_id: int) -> ZoneInfo:
    zone = db.scalar(select(Channel.timezone).where(Channel.id == channel_id)) or "UTC"
    try:
        return ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _add_best_period(
    db: Session,
    channel_id: int,
    streams: list[Stream],
    per_stream: dict[int, float],
    add,
) -> None:
    """Time-of-day slot that pays best per hour, in the channel's own timezone.
    Needs 2+ paying slots to compare."""
    tz = _channel_tz(db, channel_id)
    seconds, groups = _hours_by(
        streams, lambda s: _period(s.started_at.astimezone(tz).hour)
    )
    rates = _per_hour_rates(seconds, groups, per_stream)
    if len(rates) < 2:
        return
    best, best_rate = max(rates.items(), key=lambda item: item[1])
    worst, worst_rate = min(rates.items(), key=lambda item: item[1])
    if worst_rate > 0 and best_rate >= worst_rate * PERIOD_LIFT_MIN:
        add(
            f"Lives no período da {best} rendem US$ {best_rate:.2f}/h, "
            f"{best_rate / worst_rate:.1f}x as da {worst}: concentre nesse horário."
        )


def _add_subscriber_trend(db: Session, ready_ids: list[int], add) -> None:
    """Subscribers gained versus lost across the analyzed streams. Comparative
    by construction (gain vs loss), unlike a bare active-sub count."""
    if not ready_ids:
        return
    gained = _count_events(db, ready_ids, SUBSCRIBE)
    lost = _count_events(db, ready_ids, SUB_END)
    if gained + lost == 0:
        return
    add(
        f"Nas lives analisadas você ganhou {gained} e perdeu {lost} assinante(s) "
        f"(saldo {gained - lost:+d})."
    )


def _count_events(db: Session, ready_ids: list[int], event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count()).where(
                Event.stream_id.in_(ready_ids), Event.type == event_type
            )
        )
        or 0
    )


def _add_category_engagement(db: Session, streams: list[Stream], add) -> None:
    """Category whose audience talks the most (chatters / peak viewers): a
    high-engagement theme builds community, which retains subscribers. Needs
    2+ categories with viewers to compare."""
    category_of = {s.id: s.category for s in streams if s.category}
    if len(set(category_of.values())) < 2:
        return
    stream_ids = list(category_of)
    chatters = _distinct_chatters(db, stream_ids)
    peaks = _peak_viewers(db, stream_ids)

    ratios: dict[str, list[float]] = defaultdict(list)
    for stream_id, category in category_of.items():
        peak = peaks.get(stream_id, 0)
        if peak > 0:
            ratios[category].append(chatters.get(stream_id, 0) / peak)
    per_category = {cat: sum(rs) / len(rs) for cat, rs in ratios.items() if rs}
    if len(per_category) < 2:
        return
    best, best_ratio = max(per_category.items(), key=lambda item: item[1])
    worst, worst_ratio = min(per_category.items(), key=lambda item: item[1])
    if worst_ratio > 0 and best_ratio >= worst_ratio * ENGAGEMENT_LIFT_MIN:
        add(
            f"Lives de '{best}' têm {round(best_ratio * 100)}% do público no chat, "
            f"{best_ratio / worst_ratio:.1f}x '{worst}' ({round(worst_ratio * 100)}%): "
            "esse tema cria mais comunidade."
        )


def _distinct_chatters(db: Session, stream_ids: list[int]) -> dict[int, int]:
    return {
        row[0]: row[1]
        for row in db.execute(
            select(
                ChatMessage.stream_id, func.count(func.distinct(ChatMessage.author_id))
            )
            .where(ChatMessage.stream_id.in_(stream_ids))
            .group_by(ChatMessage.stream_id)
        )
    }


def _peak_viewers(db: Session, stream_ids: list[int]) -> dict[int, int]:
    return {
        row[0]: row[1]
        for row in db.execute(
            select(ViewerSample.stream_id, func.max(ViewerSample.viewer_count))
            .where(ViewerSample.stream_id.in_(stream_ids))
            .group_by(ViewerSample.stream_id)
        )
    }


def _add_top_reward(db: Session, ready_ids: list[int], add) -> None:
    """The most-redeemed channel-points reward, only when there ARE rivals to
    beat (2+ distinct rewards), so 'most redeemed' actually means something."""
    if not ready_ids:
        return
    events = db.scalars(
        select(Event).where(
            Event.stream_id.in_(ready_ids), Event.type == REDEMPTION_ADD
        )
    ).all()
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        title = ((event.payload or {}).get("reward") or {}).get("title")
        if title:
            counts[title] += 1
    if len(counts) < 2:
        return
    top, times = max(counts.items(), key=lambda item: item[1])
    add(
        f"A recompensa de pontos mais resgatada é '{top}' ({times}x), à frente das "
        "demais: destaque-a para engajar."
    )


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
