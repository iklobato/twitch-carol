"""Per-stream financial breakdown from captured money events (bits, subs,
gifts): total raised, top contributors, and which topics earned the most.
Values are estimates; empty until the channel monetizes."""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dashboard import _cited_ids, _owned_stream
from apps.api.deps import CurrentChannel, DbSession
from core.finance import (
    CHEER,
    GIFT,
    MONEY_EVENT_TYPES,
    RESUB,
    SUBSCRIBE,
    event_contributor,
    event_usd,
)
from core.models import Event, Insight, InsightType, Stream, TranscriptSegment

router = APIRouter(prefix="/api")

TOP_CONTRIBUTORS = 10
TOPIC_WINDOW_PADDING = timedelta(seconds=60)


class Contributor(BaseModel):
    login: str
    estimated_usd: float
    bits: int
    subs: int


class TopicRevenue(BaseModel):
    name: str
    estimated_usd: float
    events: int


class FinanceOut(BaseModel):
    estimated_usd: float
    total_bits: int
    total_subs: int
    total_gifts: int
    money_events: int
    top_contributors: list[Contributor]
    by_topic: list[TopicRevenue]


def _load_money_events(db: Session, stream_id: int) -> list[Event]:
    return list(
        db.scalars(
            select(Event)
            .where(Event.stream_id == stream_id)
            .where(Event.type.in_(MONEY_EVENT_TYPES))
            .order_by(Event.occurred_at)
        )
    )


def _topic_windows(db: Session, stream: Stream) -> list[tuple[str, datetime, datetime]]:
    topics = db.scalars(
        select(Insight)
        .where(Insight.stream_id == stream.id)
        .where(Insight.type == InsightType.TOPIC)
    ).all()
    windows = []
    for topic in topics:
        segment_ids = _cited_ids(topic, "segment_ids")
        if not segment_ids:
            continue
        bounds = db.execute(
            select(
                func.min(TranscriptSegment.started_at),
                func.max(TranscriptSegment.ended_at),
            )
            .where(TranscriptSegment.id.in_(segment_ids))
            .where(TranscriptSegment.stream_id == stream.id)
        ).one()
        if bounds[0] is None:
            continue
        name = topic.content.split("\n")[0]
        windows.append(
            (name, bounds[0] - TOPIC_WINDOW_PADDING, bounds[1] + TOPIC_WINDOW_PADDING)
        )
    return windows


@router.get("/streams/{stream_id}/finance")
def stream_finance(
    stream_id: int, channel: CurrentChannel, db: DbSession
) -> FinanceOut:
    stream = _owned_stream(db, channel, stream_id)
    events = _load_money_events(db, stream.id)

    total_usd = 0.0
    total_bits = 0
    total_subs = 0
    total_gifts = 0
    per_login_usd: dict[str, float] = defaultdict(float)
    per_login_bits: dict[str, int] = defaultdict(int)
    per_login_subs: dict[str, int] = defaultdict(int)

    for event in events:
        value = event_usd(event)
        total_usd += value
        login = event_contributor(event)
        if login:
            per_login_usd[login] += value
        if event.type == CHEER:
            total_bits += event.amount or 0
            if login:
                per_login_bits[login] += event.amount or 0
        elif event.type in (SUBSCRIBE, RESUB):
            total_subs += 1
            if login:
                per_login_subs[login] += 1
        elif event.type == GIFT:
            total_gifts += event.amount or 0
            if login:
                per_login_subs[login] += event.amount or 0

    top = sorted(per_login_usd.items(), key=lambda item: item[1], reverse=True)[
        :TOP_CONTRIBUTORS
    ]
    contributors = [
        Contributor(
            login=login,
            estimated_usd=round(usd, 2),
            bits=per_login_bits.get(login, 0),
            subs=per_login_subs.get(login, 0),
        )
        for login, usd in top
    ]

    by_topic: list[TopicRevenue] = []
    for name, start, end in _topic_windows(db, stream):
        in_window = [e for e in events if start <= e.occurred_at < end]
        if not in_window:
            continue
        by_topic.append(
            TopicRevenue(
                name=name,
                estimated_usd=round(sum(event_usd(e) for e in in_window), 2),
                events=len(in_window),
            )
        )
    by_topic.sort(key=lambda topic: topic.estimated_usd, reverse=True)

    return FinanceOut(
        estimated_usd=round(total_usd, 2),
        total_bits=total_bits,
        total_subs=total_subs,
        total_gifts=total_gifts,
        money_events=len(events),
        top_contributors=contributors,
        by_topic=by_topic,
    )
