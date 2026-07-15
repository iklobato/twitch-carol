"""Derived follower signals: where follows come from and whether they're real.

- raid attribution: follows that arrived right after an incoming raid
- fake-follow score: per-follower risk from account age/avatar/bio/timing
- follow velocity + anomalies: daily follow series with spike detection
- topic -> follow: transcript topics that coincided with follow bursts

Follow timing during streams comes from `channel.follow` events; the long-run
velocity series uses the followers table's followed_at (full history).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Event, Follower, Insight, InsightType, TranscriptSegment

FOLLOW_EVENT = "channel.follow"
RAID_EVENT = "channel.raid"

RAID_WINDOW = timedelta(minutes=15)
TOPIC_PADDING = timedelta(seconds=60)

# Fake-follow scoring: each true signal adds its weight; total >= threshold flags.
YOUNG_ACCOUNT_DAYS = 30
FRESH_FOLLOW_DAYS = 7
SCORE_YOUNG = 2
SCORE_NO_AVATAR = 1
SCORE_NO_BIO = 1
SCORE_FRESH_FOLLOW = 2
SUSPICIOUS_THRESHOLD = 4
SUSPICIOUS_LIMIT = 25

# Velocity anomaly: a day whose follow count exceeds mean + K*stdev is a spike.
ANOMALY_K = 2.0
MIN_DAYS_FOR_ANOMALY = 7
DEFAULT_AVATAR_MARKER = "user-default"


@dataclass(frozen=True)
class RaidAttribution:
    raider_login: str | None
    viewers: int
    at: datetime
    follows_after: int


@dataclass(frozen=True)
class SuspiciousFollower:
    login: str
    display_name: str | None
    score: int
    reasons: list[str]


@dataclass(frozen=True)
class VelocityDay:
    day: str
    follows: int
    is_spike: bool


@dataclass(frozen=True)
class TopicFollows:
    topic: str
    follows: int


def raid_attribution(db: Session, channel_id: int) -> list[RaidAttribution]:
    """For each incoming raid, how many follows landed within RAID_WINDOW after
    it: which raids actually converted."""
    events = list(
        db.scalars(
            select(Event)
            .where(Event.channel_id == channel_id)
            .where(Event.type.in_([RAID_EVENT, FOLLOW_EVENT]))
            .order_by(Event.occurred_at)
        )
    )
    follows = sorted(e.occurred_at for e in events if e.type == FOLLOW_EVENT)
    results: list[RaidAttribution] = []
    for raid in (e for e in events if e.type == RAID_EVENT):
        window_end = raid.occurred_at + RAID_WINDOW
        count = sum(1 for f in follows if raid.occurred_at <= f < window_end)
        payload = raid.payload or {}
        results.append(
            RaidAttribution(
                raider_login=payload.get("from_broadcaster_user_login"),
                viewers=raid.amount or 0,
                at=raid.occurred_at,
                follows_after=count,
            )
        )
    results.sort(key=lambda r: r.follows_after, reverse=True)
    return results


def _fake_follow_reasons(follower: Follower, now: datetime) -> list[str]:
    reasons: list[str] = []
    created = follower.account_created_at
    if created is not None and (now - created).days < YOUNG_ACCOUNT_DAYS:
        reasons.append("young")
    if (
        created is not None
        and (follower.followed_at - created).days < FRESH_FOLLOW_DAYS
    ):
        reasons.append("fresh_follow")
    image = follower.profile_image_url or ""
    if not image or DEFAULT_AVATAR_MARKER in image:
        reasons.append("no_avatar")
    if not (follower.description or "").strip():
        reasons.append("no_bio")
    return reasons


_REASON_WEIGHT = {
    "young": SCORE_YOUNG,
    "fresh_follow": SCORE_FRESH_FOLLOW,
    "no_avatar": SCORE_NO_AVATAR,
    "no_bio": SCORE_NO_BIO,
}
_REASON_LABEL = {
    "young": "conta recém-criada",
    "fresh_follow": "seguiu logo após criar a conta",
    "no_avatar": "sem foto de perfil",
    "no_bio": "sem bio",
}


def suspicious_followers(
    db: Session, channel_id: int, now: datetime | None = None
) -> list[SuspiciousFollower]:
    """Followers whose profile looks bot-like. Only enriched rows can be scored
    (account age/avatar/bio come from Helix)."""
    reference = now if now is not None else datetime.now(UTC)
    flagged: list[SuspiciousFollower] = []
    for follower in db.scalars(
        select(Follower)
        .where(Follower.channel_id == channel_id)
        .where(Follower.enriched_at.is_not(None))
    ):
        reasons = _fake_follow_reasons(follower, reference)
        score = sum(_REASON_WEIGHT[r] for r in reasons)
        if score >= SUSPICIOUS_THRESHOLD:
            flagged.append(
                SuspiciousFollower(
                    login=follower.login,
                    display_name=follower.display_name,
                    score=score,
                    reasons=[_REASON_LABEL[r] for r in reasons],
                )
            )
    flagged.sort(key=lambda f: f.score, reverse=True)
    return flagged[:SUSPICIOUS_LIMIT]


def follow_velocity(db: Session, channel_id: int) -> list[VelocityDay]:
    """Daily follow counts (from followed_at) with spikes flagged where a day
    exceeds mean + K*stdev: viral moments or bot bursts stand out."""
    per_day: dict[str, int] = defaultdict(int)
    for followed_at in db.scalars(
        select(Follower.followed_at).where(Follower.channel_id == channel_id)
    ):
        per_day[followed_at.strftime("%Y-%m-%d")] += 1
    if not per_day:
        return []
    counts = list(per_day.values())
    threshold = (
        mean(counts) + ANOMALY_K * pstdev(counts)
        if len(counts) >= MIN_DAYS_FOR_ANOMALY
        else float("inf")
    )
    return [
        VelocityDay(day=day, follows=per_day[day], is_spike=per_day[day] > threshold)
        for day in sorted(per_day)
    ]


def topic_to_follows(db: Session, channel_id: int) -> list[TopicFollows]:
    """Transcript topics whose time window overlapped follow events: what you
    were talking about when new people followed."""
    from apps.api.dashboard import _cited_ids

    follows = sorted(
        db.scalars(
            select(Event.occurred_at)
            .where(Event.channel_id == channel_id)
            .where(Event.type == FOLLOW_EVENT)
        )
    )
    if not follows:
        return []
    topics = list(db.scalars(select(Insight).where(Insight.type == InsightType.TOPIC)))
    segment_ids = {i for t in topics for i in _cited_ids(t, "segment_ids")}
    if not segment_ids:
        return []
    bounds = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(
                TranscriptSegment.id,
                TranscriptSegment.started_at,
                TranscriptSegment.ended_at,
            ).where(TranscriptSegment.id.in_(segment_ids))
        )
    }
    per_topic: dict[str, int] = defaultdict(int)
    for topic in topics:
        segs = [bounds[i] for i in _cited_ids(topic, "segment_ids") if i in bounds]
        if not segs:
            continue
        start = min(s[0] for s in segs) - TOPIC_PADDING
        end = max(s[1] for s in segs) + TOPIC_PADDING
        name = topic.content.split("\n")[0]
        per_topic[name] += sum(1 for f in follows if start <= f < end)
    ranked = [
        TopicFollows(topic=name, follows=count)
        for name, count in per_topic.items()
        if count > 0
    ]
    ranked.sort(key=lambda t: t.follows, reverse=True)
    return ranked
