"""Channel-level analytics across all of a channel's streams: loyal chatters,
best time to go live, growth, and recurring topics. All numbers from SQL."""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Float, func, select

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
from core.models import (
    ChatMessage,
    Event,
    Follower,
    Insight,
    InsightType,
    PastBroadcast,
    Stream,
    StreamStatus,
    TranscriptSegment,
    ViewerSample,
)

router = APIRouter(prefix="/api/channel")

LOYAL_LIMIT = 20
TOPIC_LIMIT = 10
CONTRIBUTORS_LIMIT = 10
MONETIZING_TOPIC_LIMIT = 8
PAST_BROADCAST_LIMIT = 20
TOPIC_WINDOW_PADDING = timedelta(seconds=60)
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
    estimated_usd: float


class RecurringTopic(BaseModel):
    name: str
    streams: int


class PastBroadcastOut(BaseModel):
    title: str | None
    published_at: datetime
    duration_seconds: int
    view_count: int
    url: str


class TopContributor(BaseModel):
    login: str
    estimated_usd: float
    streams: int


class MonetizingTopic(BaseModel):
    name: str
    estimated_usd: float
    streams: int


class ChannelFinance(BaseModel):
    total_estimated_usd: float
    total_bits: int
    total_subs: int
    total_gifts: int
    top_contributors: list[TopContributor]
    top_monetizing_topics: list[MonetizingTopic]


class ChannelOverview(BaseModel):
    total_streams: int
    total_messages: int
    unique_chatters: int
    total_followers_gained: int
    loyal_chatters: list[LoyalChatter]
    best_weekdays: list[WeekdaySlot]
    growth: list[GrowthPoint]
    recurring_topics: list[RecurringTopic]
    finance: ChannelFinance
    past_broadcasts: list[PastBroadcastOut]


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
    """Union of the backfilled followers table and live-captured follow events,
    so follows recorded before the backfill existed still count."""
    from_table = db.scalars(
        select(Follower.login).where(Follower.channel_id == channel_id)
    )
    from_events = db.scalars(
        select(Event.payload["user_login"].astext)
        .where(Event.channel_id == channel_id)
        .where(Event.type == FOLLOW_EVENT_TYPE)
    )
    return {login for login in [*from_table, *from_events] if login}


def _past_broadcasts(db: DbSession, channel_id: int) -> list[PastBroadcastOut]:
    rows = db.scalars(
        select(PastBroadcast)
        .where(PastBroadcast.channel_id == channel_id)
        .order_by(PastBroadcast.published_at.desc())
        .limit(PAST_BROADCAST_LIMIT)
    )
    return [
        PastBroadcastOut(
            title=row.title,
            published_at=row.published_at,
            duration_seconds=row.duration_seconds,
            view_count=row.view_count,
            url=row.url,
        )
        for row in rows
    ]


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
    revenue: dict[int, float] = defaultdict(float)
    for event in db.scalars(
        select(Event)
        .where(Event.stream_id.in_(stream_ids))
        .where(Event.type.in_(MONEY_EVENT_TYPES))
    ):
        revenue[event.stream_id] += event_usd(event)
    return [
        GrowthPoint(
            stream_id=s.id,
            started_at=s.started_at,
            title=s.title,
            peak_viewers=int(peaks.get(s.id, 0)),
            avg_viewers=round(float(avgs.get(s.id, 0) or 0), 1),
            followers_gained=int(follows.get(s.id, 0)),
            messages=int(msgs.get(s.id, 0)),
            estimated_usd=round(revenue.get(s.id, 0.0), 2),
        )
        for s in streams
    ]


def _topic_windows_by_stream(
    db: DbSession, stream_ids: list[int]
) -> dict[int, list[tuple[str, datetime, datetime]]]:
    """For each stream, its topics' (name, window_start, window_end), where the
    window comes from the topic's cited transcript segments."""
    from apps.api.dashboard import _cited_ids

    topics = db.scalars(
        select(Insight)
        .where(Insight.stream_id.in_(stream_ids))
        .where(Insight.type == InsightType.TOPIC)
    ).all()
    segment_ids = {i for t in topics for i in _cited_ids(t, "segment_ids")}
    bounds: dict[int, tuple[datetime, datetime]] = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(
                TranscriptSegment.id,
                TranscriptSegment.started_at,
                TranscriptSegment.ended_at,
            ).where(TranscriptSegment.id.in_(segment_ids))
        )
    }
    windows: dict[int, list[tuple[str, datetime, datetime]]] = defaultdict(list)
    for topic in topics:
        segs = [bounds[i] for i in _cited_ids(topic, "segment_ids") if i in bounds]
        if not segs:
            continue
        start = min(s[0] for s in segs) - TOPIC_WINDOW_PADDING
        end = max(s[1] for s in segs) + TOPIC_WINDOW_PADDING
        windows[topic.stream_id].append((topic.content.split("\n")[0], start, end))
    return windows


def _channel_finance(
    db: DbSession, channel_id: int, ready_ids: list[int]
) -> ChannelFinance:
    events = db.scalars(
        select(Event)
        .where(Event.channel_id == channel_id)
        .where(Event.type.in_(MONEY_EVENT_TYPES))
    ).all()

    total = 0.0
    total_bits = 0
    total_subs = 0
    total_gifts = 0
    per_login: dict[str, float] = defaultdict(float)
    per_login_streams: dict[str, set[int]] = defaultdict(set)
    for event in events:
        value = event_usd(event)
        total += value
        login = event_contributor(event)
        if login:
            per_login[login] += value
            per_login_streams[login].add(event.stream_id)
        if event.type == CHEER:
            total_bits += event.amount or 0
        elif event.type in (SUBSCRIBE, RESUB):
            total_subs += 1
        elif event.type == GIFT:
            total_gifts += event.amount or 0

    ranked = sorted(per_login.items(), key=lambda item: item[1], reverse=True)[
        :CONTRIBUTORS_LIMIT
    ]
    contributors = [
        TopContributor(
            login=login,
            estimated_usd=round(usd, 2),
            streams=len(per_login_streams[login]),
        )
        for login, usd in ranked
    ]

    topic_usd: dict[str, float] = defaultdict(float)
    topic_streams: dict[str, set[int]] = defaultdict(set)
    windows = _topic_windows_by_stream(db, ready_ids) if ready_ids else {}
    for event in events:
        for name, start, end in windows.get(event.stream_id, []):
            if start <= event.occurred_at < end:
                topic_usd[name] += event_usd(event)
                topic_streams[name].add(event.stream_id)
    monetizing = sorted(topic_usd.items(), key=lambda item: item[1], reverse=True)[
        :MONETIZING_TOPIC_LIMIT
    ]
    top_topics = [
        MonetizingTopic(
            name=name, estimated_usd=round(usd, 2), streams=len(topic_streams[name])
        )
        for name, usd in monetizing
        if usd > 0
    ]

    return ChannelFinance(
        total_estimated_usd=round(total, 2),
        total_bits=total_bits,
        total_subs=total_subs,
        total_gifts=total_gifts,
        top_contributors=contributors,
        top_monetizing_topics=top_topics,
    )


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
        finance=_channel_finance(db, channel.id, ready_ids),
        past_broadcasts=_past_broadcasts(db, channel.id),
    )
