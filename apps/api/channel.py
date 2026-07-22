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
    BitsLeader,
    ChannelRecommendation,
    ChatMessage,
    Event,
    Follower,
    Goal,
    Insight,
    InsightType,
    PastBroadcast,
    Stream,
    StreamStatus,
    Subscription,
    TranscriptSegment,
    ViewerSample,
    Vip,
)

router = APIRouter(prefix="/api/channel")

LOYAL_LIMIT = 20
TOPIC_LIMIT = 10
CONTRIBUTORS_LIMIT = 10
MONETIZING_TOPIC_LIMIT = 8
PAST_BROADCAST_LIMIT = 20
CONTENT_LIMIT = 8
SECONDS_PER_HOUR = 3600
POINTS_REWARD_LIMIT = 8
AD_WINDOW = timedelta(seconds=90)
TOPIC_WINDOW_PADDING = timedelta(seconds=60)
FOLLOW_EVENT_TYPE = "channel.follow"
SUB_END = "channel.subscription.end"
BITS_LEADER_LIMIT = 10
HYPE_TRAIN_END = "channel.hype_train.end"
REDEMPTION_ADD = "channel.channel_points_custom_reward_redemption.add"
AD_BREAK = "channel.ad_break.begin"
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


class ContentBucket(BaseModel):
    category: str
    estimated_usd: float
    usd_per_hour: float
    streams: int
    avg_peak_viewers: float


class HypeTrainStats(BaseModel):
    count: int
    best_level: int
    total_contributed: int


class PointsReward(BaseModel):
    title: str
    redemptions: int


class AdImpact(BaseModel):
    breaks: int
    total_seconds: int
    avg_viewer_change_pct: float | None


class Engagement(BaseModel):
    hype_train: HypeTrainStats
    top_rewards: list[PointsReward]
    ads: AdImpact


class GoalOut(BaseModel):
    goal_type: str
    description: str | None
    current_amount: int
    target_amount: int
    pct: float
    created_at: datetime | None


class Community(BaseModel):
    engaged_viewer_pct: float | None
    vips: list[str]
    goals: list[GoalOut]


class TierCount(BaseModel):
    tier: str
    count: int


class BitsLeaderOut(BaseModel):
    login: str
    score: int


class Subscribers(BaseModel):
    total: int
    tiers: list[TierCount]
    gifted_pct: float
    subs_ended: int
    # In-window sub flow. churn_pct = ended / (active at window start); None when
    # there were no active subs to churn from.
    subs_gained: int
    net_subs: int
    churn_pct: float | None
    top_bits: list[BitsLeaderOut]


class RecommendationOut(BaseModel):
    content: str
    facts: list[str]


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
    connected_at: datetime
    scopes: list[str]
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
    content_revenue: list[ContentBucket]
    engagement: Engagement
    community: Community
    subscribers: Subscribers
    recommendations: list[RecommendationOut]


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


def _content_revenue(
    db: DbSession, channel_id: int, ready_ids: list[int]
) -> list[ContentBucket]:
    """Revenue and efficiency ($/hour) grouped by the stream's category, so the
    streamer sees which content actually converts, not just which drew viewers."""
    if not ready_ids:
        return []
    streams = db.execute(
        select(Stream.id, Stream.category, Stream.started_at, Stream.ended_at).where(
            Stream.id.in_(ready_ids)
        )
    ).all()
    revenue: dict[int, float] = defaultdict(float)
    for event in db.scalars(
        select(Event)
        .where(Event.stream_id.in_(ready_ids))
        .where(Event.type.in_(MONEY_EVENT_TYPES))
    ):
        revenue[event.stream_id] += event_usd(event)
    peaks: dict[int, int] = {
        row[0]: row[1]
        for row in db.execute(
            select(ViewerSample.stream_id, func.max(ViewerSample.viewer_count))
            .where(ViewerSample.stream_id.in_(ready_ids))
            .group_by(ViewerSample.stream_id)
        )
    }

    usd: dict[str, float] = defaultdict(float)
    seconds: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    peak_sum: dict[str, int] = defaultdict(int)
    for stream_id, category, started_at, ended_at in streams:
        if not category:
            continue  # can't attribute revenue to unknown content
        usd[category] += revenue.get(stream_id, 0.0)
        counts[category] += 1
        peak_sum[category] += int(peaks.get(stream_id, 0))
        if ended_at is not None:
            seconds[category] += (ended_at - started_at).total_seconds()

    buckets = [
        ContentBucket(
            category=category,
            estimated_usd=round(total, 2),
            usd_per_hour=(
                round(total / (seconds[category] / SECONDS_PER_HOUR), 2)
                if seconds[category] > 0
                else 0.0
            ),
            streams=counts[category],
            avg_peak_viewers=round(peak_sum[category] / counts[category], 1),
        )
        for category, total in usd.items()
    ]
    buckets.sort(key=lambda bucket: bucket.estimated_usd, reverse=True)
    return buckets[:CONTENT_LIMIT]


def _subscribers(db: DbSession, channel_id: int, ready_ids: list[int]) -> Subscribers:
    """Subscriber mix (tiers, gifted share), churn from subscription.end events,
    and the all-time bits leaderboard. Snapshot data is affiliate-only, so this
    is empty until the channel monetizes."""
    tier_rows = db.execute(
        select(Subscription.tier, func.count())
        .where(Subscription.channel_id == channel_id)
        .group_by(Subscription.tier)
        .order_by(Subscription.tier)
    ).all()
    tiers = [TierCount(tier=tier, count=count) for tier, count in tier_rows]
    total = sum(t.count for t in tiers)
    gifted = db.scalar(
        select(func.count()).where(
            Subscription.channel_id == channel_id, Subscription.is_gift.is_(True)
        )
    )
    subs_ended = 0
    subs_gained = 0
    if ready_ids:
        subs_ended = int(
            db.scalar(
                select(func.count()).where(
                    Event.stream_id.in_(ready_ids), Event.type == SUB_END
                )
            )
            or 0
        )
        new_subs = int(
            db.scalar(
                select(func.count()).where(
                    Event.stream_id.in_(ready_ids), Event.type == SUBSCRIBE
                )
            )
            or 0
        )
        gifted_subs = int(
            db.scalar(
                select(func.coalesce(func.sum(Event.amount), 0)).where(
                    Event.stream_id.in_(ready_ids), Event.type == GIFT
                )
            )
            or 0
        )
        subs_gained = new_subs + gifted_subs
    active_at_start = total - subs_gained + subs_ended
    churn_pct = (
        round(subs_ended / active_at_start * 100, 1) if active_at_start > 0 else None
    )
    top_bits = [
        BitsLeaderOut(login=login, score=score)
        for login, score in db.execute(
            select(BitsLeader.login, BitsLeader.score)
            .where(BitsLeader.channel_id == channel_id)
            .order_by(BitsLeader.rank)
            .limit(BITS_LEADER_LIMIT)
        )
    ]
    return Subscribers(
        total=total,
        tiers=tiers,
        gifted_pct=round((gifted or 0) / total * 100, 1) if total else 0.0,
        subs_ended=subs_ended,
        subs_gained=subs_gained,
        net_subs=subs_gained - subs_ended,
        churn_pct=churn_pct,
        top_bits=top_bits,
    )


def _goals(db: DbSession, channel_id: int) -> list[GoalOut]:
    """Current creator-goal snapshot (sub/follower/bits progress)."""
    return [
        GoalOut(
            goal_type=goal.goal_type,
            description=goal.description,
            current_amount=goal.current_amount,
            target_amount=goal.target_amount,
            pct=(
                round(goal.current_amount / goal.target_amount * 100, 1)
                if goal.target_amount > 0
                else 0.0
            ),
            created_at=goal.created_at,
        )
        for goal in db.scalars(
            select(Goal).where(Goal.channel_id == channel_id).order_by(Goal.goal_type)
        )
    ]


def _community(db: DbSession, channel_id: int, ready_ids: list[int]) -> Community:
    """Goals, VIPs, and how much of the audience actually chats (a low chat
    rate means paying viewers are lurking, not engaged)."""
    vips = list(
        db.scalars(
            select(Vip.login).where(Vip.channel_id == channel_id).order_by(Vip.login)
        )
    )
    return Community(
        engaged_viewer_pct=_engaged_viewer_pct(db, ready_ids),
        vips=vips,
        goals=_goals(db, channel_id),
    )


def _engaged_viewer_pct(db: DbSession, ready_ids: list[int]) -> float | None:
    """Mean over streams of (distinct chatters / peak viewers) as a percent."""
    if not ready_ids:
        return None
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


def _engagement(db: DbSession, ready_ids: list[int]) -> Engagement:
    """Non-money engagement mechanics that drive revenue: hype trains, the
    channel-points economy, and how ad breaks move viewership."""
    if not ready_ids:
        return Engagement(
            hype_train=HypeTrainStats(count=0, best_level=0, total_contributed=0),
            top_rewards=[],
            ads=AdImpact(breaks=0, total_seconds=0, avg_viewer_change_pct=None),
        )
    events = db.scalars(
        select(Event)
        .where(Event.stream_id.in_(ready_ids))
        .where(Event.type.in_([HYPE_TRAIN_END, REDEMPTION_ADD, AD_BREAK]))
    ).all()

    hype = [e for e in events if e.type == HYPE_TRAIN_END]
    hype_stats = HypeTrainStats(
        count=len(hype),
        best_level=max(
            (int((e.payload or {}).get("level", 0)) for e in hype), default=0
        ),
        total_contributed=sum(e.amount or 0 for e in hype),
    )

    reward_counts: dict[str, int] = defaultdict(int)
    for event in events:
        if event.type != REDEMPTION_ADD:
            continue
        title = ((event.payload or {}).get("reward") or {}).get("title")
        if title:
            reward_counts[title] += 1
    top_rewards = [
        PointsReward(title=title, redemptions=count)
        for title, count in sorted(
            reward_counts.items(), key=lambda item: item[1], reverse=True
        )[:POINTS_REWARD_LIMIT]
    ]

    ad_events = [e for e in events if e.type == AD_BREAK]
    ads = AdImpact(
        breaks=len(ad_events),
        total_seconds=sum(e.amount or 0 for e in ad_events),
        avg_viewer_change_pct=_ad_viewer_change(db, ad_events),
    )
    return Engagement(hype_train=hype_stats, top_rewards=top_rewards, ads=ads)


def _ad_viewer_change(db: DbSession, ad_events: list[Event]) -> float | None:
    """Mean viewer change from just before to just after an ad break, as a
    percent. Negative means ads cost viewers."""
    changes: list[float] = []
    for event in ad_events:
        before = db.scalar(
            select(func.avg(ViewerSample.viewer_count)).where(
                ViewerSample.stream_id == event.stream_id,
                ViewerSample.sampled_at >= event.occurred_at - AD_WINDOW,
                ViewerSample.sampled_at < event.occurred_at,
            )
        )
        after = db.scalar(
            select(func.avg(ViewerSample.viewer_count)).where(
                ViewerSample.stream_id == event.stream_id,
                ViewerSample.sampled_at >= event.occurred_at,
                ViewerSample.sampled_at < event.occurred_at + AD_WINDOW,
            )
        )
        if before and after and before > 0:
            changes.append((float(after) - float(before)) / float(before) * 100)
    if not changes:
        return None
    return round(sum(changes) / len(changes), 1)


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


def _recommendations(db: DbSession, channel_id: int) -> list[RecommendationOut]:
    rows = db.scalars(
        select(ChannelRecommendation)
        .where(ChannelRecommendation.channel_id == channel_id)
        .order_by(ChannelRecommendation.id)
    )
    return [
        RecommendationOut(content=row.content, facts=row.evidence.get("facts", []))
        for row in rows
    ]


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
        connected_at=channel.created_at,
        scopes=channel.scopes,
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
        content_revenue=_content_revenue(db, channel.id, ready_ids),
        engagement=_engagement(db, ready_ids),
        community=_community(db, channel.id, ready_ids),
        subscribers=_subscribers(db, channel.id, ready_ids),
        recommendations=_recommendations(db, channel.id),
    )
