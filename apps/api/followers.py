"""The "Meus seguidores" page: metrics, profiles, aggregate composition of the
follower base, and LLM decisions about it. Everything from SQL + the enrichment
the connect backfill pulled from Helix Get Users."""

from collections import Counter, defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from apps.api.deps import CurrentChannel, DbSession
from core.models import ChatMessage, Follower, FollowerRecommendation

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


class FollowersOverview(BaseModel):
    kpis: FollowerKpis
    growth: list[GrowthBucket]
    recent: list[ProfileOut]
    notable: list[ProfileOut]
    composition: Composition
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

    return FollowersOverview(
        kpis=_kpis(followers, now),
        growth=_growth(followers),
        recent=[_profile(f) for f in recent],
        notable=[_profile(f) for f in notable[:NOTABLE_LIMIT]],
        composition=_composition(followers, chatter_logins, now),
        recommendations=_recommendations(db, channel.id),
    )
