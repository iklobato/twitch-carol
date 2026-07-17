"""All-time record tracking across a channel's lives.

Fourteen per-live metrics (chat, audience, monetization) are computed from data
already captured. When a freshly analyzed live beats the channel's prior best
for a metric, a StreamRecord row is written, so the table is a HISTORY of
record-breaking lives (not every live). The current record for a metric is the
max-value row per (channel, metric); the "Suas lives" badges and the AI facts
both read from there.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.finance import CHEER, GIFT, MONEY_EVENT_TYPES, RESUB, SUBSCRIBE, event_usd
from core.models import (
    ChatMessage,
    Event,
    Stream,
    StreamRecord,
    StreamStatus,
    ViewerSample,
)

FOLLOW = "channel.follow"
RAID = "channel.raid"


class RecordMetric(enum.StrEnum):
    MESSAGES = "messages"
    CHATTERS = "chatters"
    EVENTS = "events"
    FOLLOWS = "follows"
    PEAK_VIEWERS = "peak_viewers"
    AVG_VIEWERS = "avg_viewers"
    DURATION_MINUTES = "duration_minutes"
    SUBS = "subs"
    GIFTS = "gifts"
    BITS = "bits"
    RAIDS = "raids"
    REVENUE_USD = "revenue_usd"
    MESSAGES_PER_MIN = "messages_per_min"
    RESUBS = "resubs"


LABELS: dict[RecordMetric, str] = {
    RecordMetric.MESSAGES: "mensagens no chat",
    RecordMetric.CHATTERS: "chatters únicos",
    RecordMetric.EVENTS: "eventos",
    RecordMetric.FOLLOWS: "seguidores ganhos",
    RecordMetric.PEAK_VIEWERS: "pico de viewers",
    RecordMetric.AVG_VIEWERS: "média de viewers",
    RecordMetric.DURATION_MINUTES: "duração",
    RecordMetric.SUBS: "inscrições",
    RecordMetric.GIFTS: "subs presenteados",
    RecordMetric.BITS: "bits",
    RecordMetric.RAIDS: "raids recebidos",
    RecordMetric.REVENUE_USD: "receita estimada",
    RecordMetric.MESSAGES_PER_MIN: "ritmo de chat (msgs/min)",
    RecordMetric.RESUBS: "resubs",
}


def _fmt_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def _fmt_dec(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _fmt_min(value: float) -> str:
    return f"{value:.0f} min"


def _fmt_usd(value: float) -> str:
    return f"US$ {value:.2f}".replace(".", ",")


_FORMATTERS: dict[RecordMetric, Callable[[float], str]] = {
    RecordMetric.AVG_VIEWERS: _fmt_dec,
    RecordMetric.MESSAGES_PER_MIN: _fmt_dec,
    RecordMetric.DURATION_MINUTES: _fmt_min,
    RecordMetric.REVENUE_USD: _fmt_usd,
}


def format_value(metric: RecordMetric, value: float) -> str:
    return _FORMATTERS.get(metric, _fmt_int)(value)


def compute_stream_metrics(db: Session, stream: Stream) -> dict[RecordMetric, float]:
    """The fourteen record metrics for one live, from already-captured data."""
    messages, chatters = db.execute(
        select(func.count(), func.count(func.distinct(ChatMessage.author_id))).where(
            ChatMessage.stream_id == stream.id
        )
    ).one()
    peak_viewers, avg_viewers = db.execute(
        select(
            func.coalesce(func.max(ViewerSample.viewer_count), 0),
            func.coalesce(func.avg(ViewerSample.viewer_count), 0),
        ).where(ViewerSample.stream_id == stream.id)
    ).one()
    by_type = db.execute(
        select(Event.type, func.count(), func.coalesce(func.sum(Event.amount), 0))
        .where(Event.stream_id == stream.id)
        .group_by(Event.type)
    ).all()
    count_by_type = {row[0]: row[1] for row in by_type}
    amount_by_type = {row[0]: row[2] for row in by_type}
    money = db.scalars(
        select(Event).where(
            Event.stream_id == stream.id, Event.type.in_(MONEY_EVENT_TYPES)
        )
    ).all()
    revenue = round(sum(event_usd(e) for e in money), 2)

    ended = stream.ended_at or stream.started_at
    duration_min = round((ended - stream.started_at).total_seconds() / 60, 1)
    msgs_per_min = round(messages / duration_min, 2) if duration_min > 0 else 0.0

    return {
        RecordMetric.MESSAGES: float(messages),
        RecordMetric.CHATTERS: float(chatters),
        RecordMetric.EVENTS: float(sum(count_by_type.values())),
        RecordMetric.FOLLOWS: float(count_by_type.get(FOLLOW, 0)),
        RecordMetric.PEAK_VIEWERS: float(peak_viewers),
        RecordMetric.AVG_VIEWERS: round(float(avg_viewers), 1),
        RecordMetric.DURATION_MINUTES: duration_min,
        RecordMetric.SUBS: float(count_by_type.get(SUBSCRIBE, 0)),
        RecordMetric.GIFTS: float(amount_by_type.get(GIFT, 0)),
        RecordMetric.BITS: float(amount_by_type.get(CHEER, 0)),
        RecordMetric.RAIDS: float(count_by_type.get(RAID, 0)),
        RecordMetric.REVENUE_USD: revenue,
        RecordMetric.MESSAGES_PER_MIN: msgs_per_min,
        RecordMetric.RESUBS: float(count_by_type.get(RESUB, 0)),
    }


def update_stream_records(db: Session, stream: Stream) -> list[RecordMetric]:
    """Recompute this live's metrics and write a record row for each metric it
    beats the channel's prior best on. Idempotent: it first drops any rows this
    live already held, so re-analysis never double-counts. Returns the metrics
    this live set a record for.

    ponytail: re-analyzing an OLD live compares against every other record row,
    including later lives, so an intermediate historical record it once held is
    not re-inserted. The current-record query stays correct; only the timeline
    of a re-run live loses that point. Fine until re-analysis order matters.
    """
    metrics = compute_stream_metrics(db, stream)
    db.execute(delete(StreamRecord).where(StreamRecord.stream_id == stream.id))
    broke: list[RecordMetric] = []
    for metric in RecordMetric:
        value = metrics[metric]
        if value <= 0:
            continue
        prior = db.scalar(
            select(func.max(StreamRecord.value)).where(
                StreamRecord.channel_id == stream.channel_id,
                StreamRecord.metric == metric.value,
            )
        )
        if prior is None or value > prior:
            db.add(
                StreamRecord(
                    channel_id=stream.channel_id,
                    stream_id=stream.id,
                    metric=metric.value,
                    value=value,
                    achieved_at=stream.started_at,
                )
            )
            broke.append(metric)
    db.flush()
    return broke


def _current_best(db: Session, channel_id: int) -> dict[str, tuple[int, float]]:
    """metric -> (stream_id, value) of the live currently holding it."""
    rows = db.execute(
        select(StreamRecord.metric, StreamRecord.stream_id, StreamRecord.value).where(
            StreamRecord.channel_id == channel_id
        )
    ).all()
    best: dict[str, tuple[int, float]] = {}
    for metric, stream_id, value in rows:
        current = best.get(metric)
        if current is None or value > current[1]:
            best[metric] = (stream_id, value)
    return best


def records_held_by_stream(db: Session, channel_id: int) -> dict[int, list[str]]:
    """stream_id -> labels of the metrics it currently holds the record for,
    in metric order (for stable badge display)."""
    best = _current_best(db, channel_id)
    held: dict[int, list[str]] = defaultdict(list)
    for metric in RecordMetric:
        current = best.get(metric.value)
        if current is not None:
            held[current[0]].append(LABELS[metric])
    return dict(held)


def add_record_facts(
    db: Session, channel_id: int, broke: list[RecordMetric], facts: list[str]
) -> None:
    """Append numbered record facts to the channel recommendation prompt so the
    AI can reference milestones (a target to beat) and celebrate a fresh record.
    Mirrors the [n]-prefix numbering of build_monetization_facts."""
    best = _current_best(db, channel_id)
    if best:
        marks = ", ".join(
            f"{format_value(m, best[m.value][1])} {LABELS[m]}"
            for m in RecordMetric
            if m.value in best
        )
        facts.append(
            f"[{len(facts) + 1}] Melhores marcas do canal (metas a superar): {marks}"
        )
    if broke:
        labels = ", ".join(LABELS[m] for m in broke)
        facts.append(
            f"[{len(facts) + 1}] A última live analisada bateu o recorde do canal "
            f"em: {labels}"
        )


def backfill_records(db: Session, channel_id: int) -> int:
    """Populate the record history for a channel's existing ready lives, oldest
    first, so each live is compared only against the ones before it. Returns the
    number of record-setting rows written. Idempotent."""
    streams = db.scalars(
        select(Stream)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
        .order_by(Stream.started_at)
    ).all()
    written = 0
    for stream in streams:
        written += len(update_stream_records(db, stream))
    return written
