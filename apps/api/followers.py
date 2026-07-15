"""The "Meus seguidores" page: metrics, profiles, aggregate composition of the
follower base, and LLM decisions about it. Everything from SQL + the enrichment
the connect backfill pulled from Helix Get Users."""

from collections import Counter, defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.deps import CurrentChannel, DbSession
from core.follower_ai import KIND_BIO, KIND_REACTIVATION, KIND_SEGMENT, build_segments
from core.follower_profiles import FollowerProfile, build_follower_profiles
from core.follower_signals import (
    follow_velocity,
    raid_attribution,
    suspicious_followers,
    topic_to_follows,
)
from core.models import (
    ChatMessage,
    Follower,
    FollowerAiInsight,
    FollowerRecommendation,
    Stream,
    StreamStatus,
)

router = APIRouter(prefix="/api/followers")

RECENT_LIMIT = 24
NOTABLE_LIMIT = 24
NEW_WINDOW_DAYS = (7, 30)
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365
AFFILIATE = "affiliate"
PARTNER = "partner"

# (label, upper bound in days); the last bucket catches everything older.
AGE_BUCKETS = (
    ("menos de 1 mês", DAYS_PER_MONTH),
    ("1 a 6 meses", 6 * DAYS_PER_MONTH),
    ("6 a 12 meses", DAYS_PER_YEAR),
    ("1 a 2 anos", 2 * DAYS_PER_YEAR),
)
AGE_BUCKET_OLDEST = "mais de 2 anos"

TOP_VALUE_LIMIT = 15
LOYAL_LIMIT = 15
# Funnel stages from widest to deepest; each implies the ones above it.
FUNNEL_STAGES = (
    ("seguidor", "Só seguem"),
    ("engajado", "Já deram chat"),
    ("inscrito", "Inscritos"),
    ("pagante", "Já pagaram (bits/subs)"),
)


class FollowerKpis(BaseModel):
    total: int
    enriched: int
    streamers: int
    affiliates: int
    partners: int
    new_7d: int
    new_30d: int
    avg_account_age_days: int | None


class GrowthBucket(BaseModel):
    month: str
    gained: int
    cumulative: int


class ProfileOut(BaseModel):
    login: str
    display_name: str | None
    profile_image_url: str | None
    description: str | None
    broadcaster_type: str | None
    followed_at: datetime
    account_created_at: datetime | None


class TypeSlice(BaseModel):
    label: str
    count: int


class AgeSlice(BaseModel):
    label: str
    count: int


class Composition(BaseModel):
    by_type: list[TypeSlice]
    by_age: list[AgeSlice]
    silent: int
    chatty: int


class RecommendationOut(BaseModel):
    content: str
    facts: list[str]


class FunnelStage(BaseModel):
    stage: str
    label: str
    count: int


class CohortRow(BaseModel):
    month: str
    size: int
    chatted: int
    subscribed: int
    paid: int


class TopFollower(BaseModel):
    login: str
    display_name: str | None
    stage: str
    messages: int
    streams_present: int
    estimated_usd: float
    sub_months: int
    last_seen: datetime | None


class RaidOut(BaseModel):
    raider_login: str | None
    viewers: int
    at: datetime
    follows_after: int


class SuspiciousOut(BaseModel):
    login: str
    display_name: str | None
    score: int
    reasons: list[str]


class VelocityDayOut(BaseModel):
    day: str
    follows: int
    is_spike: bool


class TopicFollowsOut(BaseModel):
    topic: str
    follows: int


class Signals(BaseModel):
    raids: list[RaidOut]
    suspicious: list[SuspiciousOut]
    suspicious_total: int
    velocity: list[VelocityDayOut]
    topic_follows: list[TopicFollowsOut]


class SegmentOut(BaseModel):
    key: str
    label: str
    description: str
    count: int
    examples: list[str]
    action: str | None


class ReactivationOut(BaseModel):
    who: str
    message: str


class FollowerAi(BaseModel):
    segments: list[SegmentOut]
    audience_summary: str | None
    reactivations: list[ReactivationOut]


class CollabCandidate(BaseModel):
    login: str
    display_name: str | None
    profile_image_url: str | None
    broadcaster_type: str | None
    stream_category: str | None
    stream_language: str | None
    shared_category: bool
    followed_at: datetime


class FollowersOverview(BaseModel):
    kpis: FollowerKpis
    growth: list[GrowthBucket]
    recent: list[ProfileOut]
    notable: list[ProfileOut]
    composition: Composition
    funnel: list[FunnelStage]
    cohorts: list[CohortRow]
    top_value: list[TopFollower]
    loyal_subscribers: list[TopFollower]
    signals: Signals
    ai: FollowerAi
    collab: list[CollabCandidate]
    recommendations: list[RecommendationOut]


def _profile(follower: Follower) -> ProfileOut:
    return ProfileOut(
        login=follower.login,
        display_name=follower.display_name,
        profile_image_url=follower.profile_image_url,
        description=follower.description,
        broadcaster_type=follower.broadcaster_type,
        followed_at=follower.followed_at,
        account_created_at=follower.account_created_at,
    )


def _kpis(followers: list[Follower], now: datetime) -> FollowerKpis:
    enriched = [f for f in followers if f.enriched_at is not None]
    affiliates = sum(1 for f in followers if f.broadcaster_type == AFFILIATE)
    partners = sum(1 for f in followers if f.broadcaster_type == PARTNER)
    new_7d = sum(
        1 for f in followers if (now - f.followed_at).days < NEW_WINDOW_DAYS[0]
    )
    new_30d = sum(
        1 for f in followers if (now - f.followed_at).days < NEW_WINDOW_DAYS[1]
    )
    ages = [
        (now - f.account_created_at).days
        for f in followers
        if f.account_created_at is not None
    ]
    avg_age = round(sum(ages) / len(ages)) if ages else None
    return FollowerKpis(
        total=len(followers),
        enriched=len(enriched),
        streamers=affiliates + partners,
        affiliates=affiliates,
        partners=partners,
        new_7d=new_7d,
        new_30d=new_30d,
        avg_account_age_days=avg_age,
    )


def _growth(followers: list[Follower]) -> list[GrowthBucket]:
    """Follows bucketed by calendar month, with a running cumulative total, so
    the page shows how the base grew over time."""
    per_month: dict[str, int] = defaultdict(int)
    for follower in followers:
        per_month[follower.followed_at.strftime("%Y-%m")] += 1
    cumulative = 0
    buckets: list[GrowthBucket] = []
    for month in sorted(per_month):
        cumulative += per_month[month]
        buckets.append(
            GrowthBucket(month=month, gained=per_month[month], cumulative=cumulative)
        )
    return buckets


def _age_bucket(days: int) -> str:
    for label, upper in AGE_BUCKETS:
        if days < upper:
            return label
    return AGE_BUCKET_OLDEST


def _composition(
    followers: list[Follower], chatter_logins: set[str], now: datetime
) -> Composition:
    type_counts: Counter[str] = Counter()
    for follower in followers:
        if follower.broadcaster_type is None:
            continue
        label = {AFFILIATE: "Afiliados", PARTNER: "Parceiros"}.get(
            follower.broadcaster_type, "Comuns"
        )
        type_counts[label] += 1

    age_counts: Counter[str] = Counter()
    for follower in followers:
        if follower.account_created_at is None:
            continue
        age_counts[_age_bucket((now - follower.account_created_at).days)] += 1

    chatty = sum(1 for f in followers if f.login in chatter_logins)
    return Composition(
        by_type=[TypeSlice(label=k, count=v) for k, v in type_counts.most_common()],
        by_age=_ordered_age_slices(age_counts),
        silent=len(followers) - chatty,
        chatty=chatty,
    )


def _ordered_age_slices(age_counts: Counter[str]) -> list[AgeSlice]:
    order = [label for label, _ in AGE_BUCKETS] + [AGE_BUCKET_OLDEST]
    return [
        AgeSlice(label=label, count=age_counts[label])
        for label in order
        if age_counts[label] > 0
    ]


def _funnel(profiles: list[FollowerProfile]) -> list[FunnelStage]:
    """Cumulative funnel: each stage counts everyone who reached it OR deeper,
    so 'engajado' includes subscribers and payers too."""
    order = [stage for stage, _ in FUNNEL_STAGES]
    reached: Counter[str] = Counter(profile.stage for profile in profiles)
    stages: list[FunnelStage] = []
    for depth, (stage, label) in enumerate(FUNNEL_STAGES):
        count = sum(reached[s] for s in order[depth:])
        stages.append(FunnelStage(stage=stage, label=label, count=count))
    return stages


def _cohorts(profiles: list[FollowerProfile]) -> list[CohortRow]:
    """Followers grouped by the month they followed, with how many of each
    cohort went on to chat, subscribe, or pay: retention by vintage."""
    rows: dict[str, CohortRow] = {}
    for profile in profiles:
        month = profile.followed_at.strftime("%Y-%m")
        row = rows.setdefault(
            month, CohortRow(month=month, size=0, chatted=0, subscribed=0, paid=0)
        )
        row.size += 1
        if profile.messages > 0:
            row.chatted += 1
        if profile.is_subscriber:
            row.subscribed += 1
        if profile.estimated_usd > 0:
            row.paid += 1
    return [rows[month] for month in sorted(rows)]


def _top(profile: FollowerProfile) -> TopFollower:
    return TopFollower(
        login=profile.login,
        display_name=profile.display_name,
        stage=profile.stage,
        messages=profile.messages,
        streams_present=profile.streams_present,
        estimated_usd=profile.estimated_usd,
        sub_months=profile.sub_months,
        last_seen=profile.last_seen,
    )


def _top_value(profiles: list[FollowerProfile]) -> list[TopFollower]:
    paying = [p for p in profiles if p.estimated_usd > 0]
    return [_top(p) for p in paying[:TOP_VALUE_LIMIT]]


def _loyal_subscribers(profiles: list[FollowerProfile]) -> list[TopFollower]:
    loyal = sorted(
        (p for p in profiles if p.sub_months > 0),
        key=lambda p: p.sub_months,
        reverse=True,
    )
    return [_top(p) for p in loyal[:LOYAL_LIMIT]]


COLLAB_LIMIT = 24


def _collab(db: DbSession, channel_id: int) -> list[CollabCandidate]:
    """Streamer followers ranked as collab candidates: those whose category
    overlaps yours come first (shared audience), then the rest by recency."""
    my_categories = {
        cat
        for cat in db.scalars(
            select(func.distinct(Stream.category))
            .where(Stream.channel_id == channel_id)
            .where(Stream.status == StreamStatus.READY)
        )
        if cat
    }
    streamers = db.scalars(
        select(Follower)
        .where(Follower.channel_id == channel_id)
        .where(Follower.broadcaster_type.in_((AFFILIATE, PARTNER)))
        .where(Follower.streamer_enriched_at.is_not(None))
    )
    candidates = [
        CollabCandidate(
            login=f.login,
            display_name=f.display_name,
            profile_image_url=f.profile_image_url,
            broadcaster_type=f.broadcaster_type,
            stream_category=f.stream_category,
            stream_language=f.stream_language,
            shared_category=(
                f.stream_category in my_categories if f.stream_category else False
            ),
            followed_at=f.followed_at,
        )
        for f in streamers
    ]
    candidates.sort(key=lambda c: (c.shared_category, c.followed_at), reverse=True)
    return candidates[:COLLAB_LIMIT]


def _ai(db: DbSession, channel_id: int, profiles: list[FollowerProfile]) -> FollowerAi:
    """Rule-based segments (always available) joined to the LLM's per-segment
    action, plus the audience bio summary and reactivation nudges (present only
    after a live has been analyzed)."""
    rows = list(
        db.scalars(
            select(FollowerAiInsight).where(FollowerAiInsight.channel_id == channel_id)
        )
    )
    action_by_label = {r.title: r.content for r in rows if r.kind == KIND_SEGMENT}
    summary = next((r.content for r in rows if r.kind == KIND_BIO), None)
    reactivations = [
        ReactivationOut(who=r.title or "", message=r.content)
        for r in rows
        if r.kind == KIND_REACTIVATION and r.title
    ]
    segments = [
        SegmentOut(
            key=s.key,
            label=s.label,
            description=s.description,
            count=s.count,
            examples=s.examples,
            action=action_by_label.get(s.label),
        )
        for s in build_segments(profiles)
    ]
    return FollowerAi(
        segments=segments, audience_summary=summary, reactivations=reactivations
    )


def _signals(db: DbSession, channel_id: int, now: datetime) -> Signals:
    """Derived signals: raid attribution, fake-follow risk, follow velocity with
    spikes, and topic-to-follow correlation."""
    raids = raid_attribution(db, channel_id)
    suspicious = suspicious_followers(db, channel_id, now)
    velocity = follow_velocity(db, channel_id)
    topics = topic_to_follows(db, channel_id)
    return Signals(
        raids=[
            RaidOut(
                raider_login=r.raider_login,
                viewers=r.viewers,
                at=r.at,
                follows_after=r.follows_after,
            )
            for r in raids
        ],
        suspicious=[
            SuspiciousOut(
                login=s.login,
                display_name=s.display_name,
                score=s.score,
                reasons=s.reasons,
            )
            for s in suspicious
        ],
        suspicious_total=len(suspicious),
        velocity=[
            VelocityDayOut(day=v.day, follows=v.follows, is_spike=v.is_spike)
            for v in velocity
        ],
        topic_follows=[
            TopicFollowsOut(topic=t.topic, follows=t.follows) for t in topics
        ],
    )


def _chatter_logins(db: DbSession, channel_id: int) -> set[str]:
    return set(
        db.scalars(
            select(func.distinct(ChatMessage.author_login)).where(
                ChatMessage.channel_id == channel_id
            )
        )
    )


def _recommendations(db: DbSession, channel_id: int) -> list[RecommendationOut]:
    rows = db.scalars(
        select(FollowerRecommendation)
        .where(FollowerRecommendation.channel_id == channel_id)
        .order_by(FollowerRecommendation.id)
    )
    return [
        RecommendationOut(content=row.content, facts=row.evidence.get("facts", []))
        for row in rows
    ]


@router.get("")
def followers_overview(channel: CurrentChannel, db: DbSession) -> FollowersOverview:
    now = datetime.now(UTC)
    followers = list(
        db.scalars(select(Follower).where(Follower.channel_id == channel.id))
    )
    chatter_logins = _chatter_logins(db, channel.id)

    recent = sorted(followers, key=lambda f: f.followed_at, reverse=True)[:RECENT_LIMIT]
    notable = [f for f in followers if f.broadcaster_type in (AFFILIATE, PARTNER)]
    notable.sort(key=lambda f: f.followed_at, reverse=True)

    profiles = build_follower_profiles(db, channel.id)

    return FollowersOverview(
        kpis=_kpis(followers, now),
        growth=_growth(followers),
        recent=[_profile(f) for f in recent],
        notable=[_profile(f) for f in notable[:NOTABLE_LIMIT]],
        composition=_composition(followers, chatter_logins, now),
        funnel=_funnel(profiles),
        cohorts=_cohorts(profiles),
        top_value=_top_value(profiles),
        loyal_subscribers=_loyal_subscribers(profiles),
        signals=_signals(db, channel.id, now),
        ai=_ai(db, channel.id, profiles),
        collab=_collab(db, channel.id),
        recommendations=_recommendations(db, channel.id),
    )
