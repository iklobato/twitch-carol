"""Per-stream financial breakdown from captured money events (bits, subs,
gifts): total raised, top contributors, and which topics earned the most.
Values are estimates; empty until the channel monetizes.

Also exposes the account-wide `/api/finance` overview: every monetization
signal Twitch OAuth exposes, scoped to an analysis period (30d / 90d / all).
Money numbers are estimates; the subscriber/goal blocks are *current*
snapshots (Twitch has no per-period revenue endpoint)."""

import enum
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.channel import (
    ContentBucket,
    Engagement,
    GoalOut,
    RecommendationOut,
    Subscribers,
    TopContributor,
    _content_revenue,
    _engagement,
    _goals,
    _recommendations,
    _subscribers,
)
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
from core.integrations.streamelements import StreamElementsError
from core.integrations.tips import (
    KIND_MERCH,
    KIND_TIP,
    set_streamelements_credentials,
    sync_streamelements_tips,
)
from core.models import (
    Event,
    ExternalTip,
    Insight,
    InsightType,
    LoyaltyEntry,
    Stream,
    StreamStatus,
    TranscriptSegment,
)

router = APIRouter(prefix="/api")

TOP_CONTRIBUTORS = 10
TOPIC_WINDOW_PADDING = timedelta(seconds=60)
BY_STREAM_LIMIT = 50
TOP_MOMENTS = 10


def _event_kind(event: Event) -> str:
    if event.type == CHEER:
        return "bits"
    if event.type == GIFT:
        return "gift"
    return "sub"  # SUBSCRIBE / RESUB


class Period(enum.StrEnum):
    P30 = "30d"
    P90 = "90d"
    ALL = "all"


PERIOD_DAYS = {Period.P30: 30, Period.P90: 90}


class Contributor(BaseModel):
    login: str
    estimated_usd: float
    bits: int
    subs: int


class TopicRevenue(BaseModel):
    name: str
    estimated_usd: float
    events: int


class MomentRevenue(BaseModel):
    """A single money event tied to what was happening: 'the $X sub came when you
    were on topic Y at HH:MM'. offset_seconds is from the stream start."""

    offset_seconds: int
    estimated_usd: float
    kind: str  # bits | sub | gift
    contributor: str | None
    topic: str | None


class FinanceOut(BaseModel):
    estimated_usd: float
    total_bits: int
    total_subs: int
    total_gifts: int
    money_events: int
    top_contributors: list[Contributor]
    by_topic: list[TopicRevenue]
    top_moments: list[MomentRevenue]


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

    windows = _topic_windows(db, stream)
    by_topic: list[TopicRevenue] = []
    for name, start, end in windows:
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

    def _topic_at(moment: datetime) -> str | None:
        return next(
            (name for name, start, end in windows if start <= moment < end), None
        )

    moments = [
        MomentRevenue(
            offset_seconds=int((event.occurred_at - stream.started_at).total_seconds()),
            estimated_usd=round(event_usd(event), 2),
            kind=_event_kind(event),
            contributor=event_contributor(event),
            topic=_topic_at(event.occurred_at),
        )
        for event in events
        if event_usd(event) > 0
    ]
    moments.sort(key=lambda moment: moment.estimated_usd, reverse=True)

    return FinanceOut(
        estimated_usd=round(total_usd, 2),
        total_bits=total_bits,
        total_subs=total_subs,
        total_gifts=total_gifts,
        money_events=len(events),
        top_contributors=contributors,
        by_topic=by_topic,
        top_moments=moments[:TOP_MOMENTS],
    )


# --- Account-wide finance overview (period-scoped) --------------------------


class StreamRevenue(BaseModel):
    stream_id: int
    title: str | None
    started_at: datetime
    estimated_usd: float


class FinanceOverview(BaseModel):
    period: str
    estimated_usd: float
    # External tips (StreamElements, ...) in-window. tips_usd sums the raw tip
    # amounts (currency conversion is a follow-up); total_revenue_usd is the
    # consolidated Twitch estimate + tips, the number a streamer actually cares
    # about.
    tips_usd: float
    tips_count: int
    # Merch/store sales from StreamElements (revenue Twitch never exposes).
    merch_usd: float
    total_revenue_usd: float
    # Efficiency: consolidated revenue per hour actually streamed in-window.
    streamed_hours: float
    revenue_per_hour_usd: float
    # None when there is no comparison window (period=all) or nothing earned
    # in the previous window to compare against.
    delta_pct: float | None
    total_bits: int
    total_subs: int
    total_gifts: int
    money_events: int
    top_contributors: list[TopContributor]
    by_stream: list[StreamRevenue]
    by_content: list[ContentBucket]
    engagement: Engagement
    # Subscriber tiers/leaderboard and goals are *current* Twitch snapshots, not
    # period-scoped: Twitch exposes no historical revenue. subs_ended is the one
    # period-scoped field (derived from subscription.end events in-window).
    subscribers: Subscribers
    goals: list[GoalOut]
    recommendations: list[RecommendationOut]


@dataclass(frozen=True)
class _MoneyFold:
    total_usd: float
    bits: int
    subs: int
    gifts: int
    count: int
    per_login_usd: dict[str, float]
    per_login_streams: dict[str, set[int]]
    per_stream_usd: dict[int, float]


def resolve_period_window(
    period: Period, now: datetime
) -> tuple[datetime | None, datetime | None]:
    """(start, previous_start) for the analysis period. ALL -> (None, None):
    the whole history with no comparison window."""
    days = PERIOD_DAYS.get(period)
    if days is None:
        return None, None
    return now - timedelta(days=days), now - timedelta(days=2 * days)


def _ready_streams_since(
    db: Session, channel_id: int, since: datetime | None
) -> list[Stream]:
    stmt = (
        select(Stream)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.READY)
    )
    if since is not None:
        stmt = stmt.where(Stream.started_at >= since)
    return list(db.scalars(stmt.order_by(Stream.started_at)))


def _load_money_events_for(db: Session, stream_ids: list[int]) -> list[Event]:
    if not stream_ids:
        return []
    return list(
        db.scalars(
            select(Event)
            .where(Event.stream_id.in_(stream_ids))
            .where(Event.type.in_(MONEY_EVENT_TYPES))
            .order_by(Event.occurred_at)
        )
    )


def _fold_money(events: list[Event]) -> _MoneyFold:
    total_usd = 0.0
    bits = subs = gifts = 0
    per_login_usd: dict[str, float] = defaultdict(float)
    per_login_streams: dict[str, set[int]] = defaultdict(set)
    per_stream_usd: dict[int, float] = defaultdict(float)
    for event in events:
        value = event_usd(event)
        total_usd += value
        per_stream_usd[event.stream_id] += value
        login = event_contributor(event)
        if login:
            per_login_usd[login] += value
            per_login_streams[login].add(event.stream_id)
        if event.type == CHEER:
            bits += event.amount or 0
        elif event.type in (SUBSCRIBE, RESUB):
            subs += 1
        elif event.type == GIFT:
            gifts += event.amount or 0
    return _MoneyFold(
        total_usd=total_usd,
        bits=bits,
        subs=subs,
        gifts=gifts,
        count=len(events),
        per_login_usd=per_login_usd,
        per_login_streams=per_login_streams,
        per_stream_usd=per_stream_usd,
    )


@router.get("/finance")
def finance_overview(
    channel: CurrentChannel, db: DbSession, period: Period = Period.P30
) -> FinanceOverview:
    start, prev_start = resolve_period_window(period, datetime.now(UTC))
    streams = _ready_streams_since(db, channel.id, prev_start)

    current = [s for s in streams if start is None or s.started_at >= start]
    previous: list[Stream] = []
    if start is not None and prev_start is not None:
        previous = [s for s in streams if prev_start <= s.started_at < start]
    current_ids = [s.id for s in current]
    previous_ids = {s.id for s in previous}

    events = _load_money_events_for(db, [s.id for s in streams])
    current_set = set(current_ids)
    current_fold = _fold_money([e for e in events if e.stream_id in current_set])
    previous_fold = _fold_money([e for e in events if e.stream_id in previous_ids])

    delta_pct: float | None = None
    if start is not None and previous_fold.total_usd > 0:
        delta_pct = round(
            (current_fold.total_usd - previous_fold.total_usd)
            / previous_fold.total_usd
            * 100,
            1,
        )

    ranked = sorted(
        current_fold.per_login_usd.items(), key=lambda item: item[1], reverse=True
    )[:TOP_CONTRIBUTORS]
    contributors = [
        TopContributor(
            login=login,
            estimated_usd=round(usd, 2),
            streams=len(current_fold.per_login_streams[login]),
        )
        for login, usd in ranked
    ]

    meta = {s.id: s for s in current}
    by_stream = sorted(
        (
            StreamRevenue(
                stream_id=sid,
                title=meta[sid].title,
                started_at=meta[sid].started_at,
                estimated_usd=round(usd, 2),
            )
            for sid, usd in current_fold.per_stream_usd.items()
            if usd > 0
        ),
        key=lambda row: row.started_at,
    )[:BY_STREAM_LIMIT]

    tips_usd, tips_count = _revenue_in_window(db, channel.id, start, KIND_TIP)
    merch_usd, _ = _revenue_in_window(db, channel.id, start, KIND_MERCH)
    total_revenue = current_fold.total_usd + tips_usd + merch_usd
    streamed_hours = (
        sum(
            (s.ended_at - s.started_at).total_seconds()
            for s in current
            if s.ended_at is not None
        )
        / 3600
    )
    return FinanceOverview(
        period=period.value,
        estimated_usd=round(current_fold.total_usd, 2),
        tips_usd=round(tips_usd, 2),
        tips_count=tips_count,
        merch_usd=round(merch_usd, 2),
        total_revenue_usd=round(total_revenue, 2),
        streamed_hours=round(streamed_hours, 1),
        revenue_per_hour_usd=(
            round(total_revenue / streamed_hours, 2) if streamed_hours > 0 else 0.0
        ),
        delta_pct=delta_pct,
        total_bits=current_fold.bits,
        total_subs=current_fold.subs,
        total_gifts=current_fold.gifts,
        money_events=current_fold.count,
        top_contributors=contributors,
        by_stream=by_stream,
        by_content=_content_revenue(db, channel.id, current_ids),
        engagement=_engagement(db, current_ids),
        subscribers=_subscribers(db, channel.id, current_ids),
        goals=_goals(db, channel.id),
        recommendations=_recommendations(db, channel.id),
    )


def _revenue_in_window(
    db: Session, channel_id: int, start: datetime | None, kind: str
) -> tuple[float, int]:
    stmt = select(
        func.coalesce(func.sum(ExternalTip.amount), 0.0), func.count(ExternalTip.id)
    ).where(ExternalTip.channel_id == channel_id, ExternalTip.kind == kind)
    if start is not None:
        stmt = stmt.where(ExternalTip.tipped_at >= start)
    total, count = db.execute(stmt).one()
    return float(total), int(count)


class StreamElementsConnect(BaseModel):
    account_id: str
    jwt: str


class StreamElementsResult(BaseModel):
    synced: int


@router.post("/finance/integrations/streamelements")
def connect_streamelements(
    body: StreamElementsConnect, channel: CurrentChannel, db: DbSession
) -> StreamElementsResult:
    """Store the channel's StreamElements creds (JWT encrypted) and pull tips."""
    set_streamelements_credentials(db, channel, body.account_id, body.jwt)
    try:
        synced = sync_streamelements_tips(db, channel)
    except StreamElementsError as err:
        raise HTTPException(status_code=502, detail=f"StreamElements: {err}") from err
    return StreamElementsResult(synced=synced)


TOP_SUPPORTERS = 20


class Supporter(BaseModel):
    tipper: str
    total: float
    currency: str
    tips_count: int
    last_tipped_at: datetime


@router.get("/finance/supporters")
def top_supporters(channel: CurrentChannel, db: DbSession) -> list[Supporter]:
    """Who tips the most: external tips grouped by tipper, biggest first. Sums
    raw amounts; mixed-currency channels get the most-recent currency label
    (currency conversion is a separate follow-up)."""
    rows = db.execute(
        select(
            ExternalTip.tipper,
            func.sum(ExternalTip.amount),
            func.count(ExternalTip.id),
            func.max(ExternalTip.tipped_at),
        )
        .where(
            ExternalTip.channel_id == channel.id,
            ExternalTip.kind == KIND_TIP,
            ExternalTip.tipper.is_not(None),
        )
        .group_by(ExternalTip.tipper)
        .order_by(func.sum(ExternalTip.amount).desc())
        .limit(TOP_SUPPORTERS)
    ).all()
    return [
        Supporter(
            tipper=tipper,
            total=round(total, 2),
            currency=_latest_currency(db, channel.id, tipper),
            tips_count=count,
            last_tipped_at=last_at,
        )
        for tipper, total, count, last_at in rows
    ]


def _latest_currency(db: Session, channel_id: int, tipper: str) -> str:
    return (
        db.scalars(
            select(ExternalTip.currency)
            .where(
                ExternalTip.channel_id == channel_id,
                ExternalTip.kind == KIND_TIP,
                ExternalTip.tipper == tipper,
            )
            .order_by(ExternalTip.tipped_at.desc())
            .limit(1)
        ).first()
        or "USD"
    )


LOYALTY_TOP = 50
TOP_PEOPLE = 20


class LoyaltyOut(BaseModel):
    username: str
    points: int
    rank: int


@router.get("/finance/loyalty")
def loyalty_leaderboard(channel: CurrentChannel, db: DbSession) -> list[LoyaltyOut]:
    """StreamElements points/watchtime leaderboard: the channel's superfans, a
    signal Twitch never exposes."""
    rows = db.scalars(
        select(LoyaltyEntry)
        .where(LoyaltyEntry.channel_id == channel.id)
        .order_by(LoyaltyEntry.rank)
        .limit(LOYALTY_TOP)
    ).all()
    return [
        LoyaltyOut(username=row.username, points=row.points, rank=row.rank)
        for row in rows
    ]


class ValuedPerson(BaseModel):
    name: str
    tips_usd: float
    loyalty_points: int


@router.get("/finance/top-people")
def top_people(channel: CurrentChannel, db: DbSession) -> list[ValuedPerson]:
    """The channel's most valuable people: off-Twitch tips + loyalty
    points/watchtime merged by name, biggest supporters first. (Subscriber
    cross-referencing is a follow-up.)"""
    tips: dict[str, float] = {}
    points: dict[str, int] = {}
    display: dict[str, str] = {}
    for name, total in db.execute(
        select(ExternalTip.tipper, func.sum(ExternalTip.amount))
        .where(
            ExternalTip.channel_id == channel.id,
            ExternalTip.kind == KIND_TIP,
            ExternalTip.tipper.is_not(None),
        )
        .group_by(ExternalTip.tipper)
    ).all():
        tips[name.lower()] = float(total)
        display[name.lower()] = name
    for entry in db.scalars(
        select(LoyaltyEntry).where(LoyaltyEntry.channel_id == channel.id)
    ):
        points[entry.username.lower()] = entry.points
        display.setdefault(entry.username.lower(), entry.username)
    people = [
        ValuedPerson(
            name=display[key],
            tips_usd=round(tips.get(key, 0.0), 2),
            loyalty_points=points.get(key, 0),
        )
        for key in tips.keys() | points.keys()
    ]
    people.sort(
        key=lambda person: (person.tips_usd, person.loyalty_points), reverse=True
    )
    return people[:TOP_PEOPLE]
