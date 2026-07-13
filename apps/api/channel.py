"""Channel-level analytics across all of a channel's streams: loyal chatters,
best time to go live, growth, and recurring topics. All numbers from SQL."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Float, func, select

from apps.api.deps import CurrentChannel, DbSession
from core.models import (
    ChatMessage,
    Event,
    Insight,
    InsightType,
    Stream,
    StreamStatus,
    ViewerSample,
)

router = APIRouter(prefix="/api/channel")

LOYAL_LIMIT = 20
TOPIC_LIMIT = 10
FOLLOW_EVENT_TYPE = "channel.follow"
WEEKDAY_LABELS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


class LoyalChatter(BaseModel):
    author_login: str
    streams_attended: int
    total_messages: int
    last_seen: datetime
    followed: bool


class WeekdaySlot(BaseModel):
    weekday: int
    label: str
    streams: int
    avg_peak_viewers: float


class GrowthPoint(BaseModel):
    stream_id: int
    started_at: datetime
    title: str | None
    peak_viewers: int
    avg_viewers: float
    followers_gained: int
    messages: int


class RecurringTopic(BaseModel):
    name: str
    streams: int


class ChannelOverview(BaseModel):
    total_streams: int
    total_messages: int
    unique_chatters: int
    total_followers_gained: int
    loyal_chatters: list[LoyalChatter]
    best_weekdays: list[WeekdaySlot]
    growth: list[GrowthPoint]
    recurring_topics: list[RecurringTopic]


def _ready_stream_ids(db: DbSession, channel_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Stream.id)
            .where(Stream.channel_id == channel_id)
            .where(Stream.status == StreamStatus.READY)
            .order_by(Stream.started_at)
        )
    )


def _loyal_chatters(
    db: DbSession, channel_id: int, follower_logins: set[str]
) -> list[LoyalChatter]:
    rows = db.execute(
        select(
            ChatMessage.author_login,
            func.count(func.distinct(ChatMessage.stream_id)),
            func.count(),
            func.max(ChatMessage.sent_at),
        )
        .where(ChatMessage.channel_id == channel_id)
        .group_by(ChatMessage.author_login)
        # loyalty = streams attended first, then volume
        .order_by(
            func.count(func.distinct(ChatMessage.stream_id)).desc(),
            func.count().desc(),
        )
        .limit(LOYAL_LIMIT)
    ).all()
    return [
        LoyalChatter(
            author_login=login,
            streams_attended=streams,
            total_messages=messages,
            last_seen=last_seen,
            followed=login in follower_logins,
        )
        for login, streams, messages, last_seen in rows
    ]


def _follower_logins(db: DbSession, channel_id: int) -> set[str]:
    rows = db.scalars(
        select(Event.payload["user_login"].astext)
        .where(Event.channel_id == channel_id)
        .where(Event.type == FOLLOW_EVENT_TYPE)
    )
    return {login for login in rows if login}


def _best_weekdays(db: DbSession, channel_id: int) -> list[WeekdaySlot]:
    # postgres dow: 0=Sunday..6=Saturday; shift to Monday=0
    dow = func.extract("dow", Stream.started_at)
    peak_per_stream = (
        select(
            Stream.id.label("stream_id"),
            dow.label("dow"),
            func.coalesce(func.max(ViewerSample.viewer_count), 0).label("peak"),
        )
        .join(ViewerSample, ViewerSample.stream_id == Stream.id, isouter=True)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
        .group_by(Stream.id, dow)
        .subquery()
    )
    rows = db.execute(
        select(
            peak_per_stream.c.dow,
            func.count(),
            func.avg(peak_per_stream.c.peak).cast(Float),
        )
        .group_by(peak_per_stream.c.dow)
        .order_by(func.avg(peak_per_stream.c.peak).desc())
    ).all()
    slots = []
    for raw_dow, streams, avg_peak in rows:
        weekday = (int(raw_dow) + 6) % 7  # sun=0 -> 6, mon=1 -> 0
        slots.append(
            WeekdaySlot(
                weekday=weekday,
                label=WEEKDAY_LABELS[weekday],
                streams=streams,
                avg_peak_viewers=round(float(avg_peak or 0), 1),
            )
        )
    return slots


def _growth(db: DbSession, channel_id: int) -> list[GrowthPoint]:
    streams = db.scalars(
        select(Stream)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
        .order_by(Stream.started_at)
    ).all()
    if not streams:
        return []
    stream_ids = [s.id for s in streams]

    peaks: dict[int, int] = {
        row[0]: row[1]
        for row in db.execute(
            select(ViewerSample.stream_id, func.max(ViewerSample.viewer_count))
            .where(ViewerSample.stream_id.in_(stream_ids))
            .group_by(ViewerSample.stream_id)
        )
    }
    avgs: dict[int, float] = {
        row[0]: float(row[1] or 0)
        for row in db.execute(
            select(
                ViewerSample.stream_id, func.avg(ViewerSample.viewer_count).cast(Float)
            )
            .where(ViewerSample.stream_id.in_(stream_ids))
            .group_by(ViewerSample.stream_id)
        )
    }
    msgs: dict[int, int] = {
        row[0]: row[1]
        for row in db.execute(
            select(ChatMessage.stream_id, func.count())
            .where(ChatMessage.stream_id.in_(stream_ids))
            .group_by(ChatMessage.stream_id)
        )
    }
    follows: dict[int, int] = {
        row[0]: row[1]
        for row in db.execute(
            select(Event.stream_id, func.count())
            .where(Event.stream_id.in_(stream_ids))
            .where(Event.type == FOLLOW_EVENT_TYPE)
            .group_by(Event.stream_id)
        )
    }
    return [
        GrowthPoint(
            stream_id=s.id,
            started_at=s.started_at,
            title=s.title,
            peak_viewers=int(peaks.get(s.id, 0)),
            avg_viewers=round(float(avgs.get(s.id, 0) or 0), 1),
            followers_gained=int(follows.get(s.id, 0)),
            messages=int(msgs.get(s.id, 0)),
        )
        for s in streams
    ]


def _recurring_topics(db: DbSession, stream_ids: list[int]) -> list[RecurringTopic]:
    if not stream_ids:
        return []
    # topic insight content is "name\ndescription"; the name is the first line
    topic_name = func.split_part(Insight.content, "\n", 1)
    rows = db.execute(
        select(topic_name, func.count(func.distinct(Insight.stream_id)))
        .where(Insight.stream_id.in_(stream_ids))
        .where(Insight.type == InsightType.TOPIC)
        .group_by(topic_name)
        .having(func.count(func.distinct(Insight.stream_id)) >= 1)
        .order_by(func.count(func.distinct(Insight.stream_id)).desc())
        .limit(TOPIC_LIMIT)
    ).all()
    return [RecurringTopic(name=name, streams=streams) for name, streams in rows]


@router.get("")
def channel_overview(channel: CurrentChannel, db: DbSession) -> ChannelOverview:
    ready_ids = _ready_stream_ids(db, channel.id)
    follower_logins = _follower_logins(db, channel.id)

    total_messages, unique_chatters = db.execute(
        select(func.count(), func.count(func.distinct(ChatMessage.author_id))).where(
            ChatMessage.channel_id == channel.id
        )
    ).one()

    return ChannelOverview(
        total_streams=len(ready_ids),
        total_messages=int(total_messages),
        unique_chatters=int(unique_chatters),
        total_followers_gained=len(follower_logins),
        loyal_chatters=_loyal_chatters(db, channel.id, follower_logins),
        best_weekdays=_best_weekdays(db, channel.id),
        growth=_growth(db, channel.id),
        recurring_topics=_recurring_topics(db, ready_ids),
    )
