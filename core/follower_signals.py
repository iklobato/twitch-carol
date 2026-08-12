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

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from core.models import Event, Follower, Insight, InsightType, Stream, TranscriptSegment

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


def _reason_flags(now: datetime) -> dict[str, ColumnElement[bool]]:
    """The fake-follow rule, defined once, as SQL.

    Written as expressions rather than as a Python loop over the base because it
    only ever returns the worst 25: scoring in Python meant loading every row of
    the channel, which for the largest real channel is 41,605 of them for 25
    answers, measured at 526ms of a 3.2s page.

    One definition on purpose. The reason names come from these same flags, so
    there is no second copy of the rule that can drift out of step with this one.
    """
    created = Follower.account_created_at
    return {
        "young": created.is_not(None)
        & (created > now - timedelta(days=YOUNG_ACCOUNT_DAYS)),
        "fresh_follow": created.is_not(None)
        & (Follower.followed_at - created < timedelta(days=FRESH_FOLLOW_DAYS)),
        "no_avatar": func.coalesce(Follower.profile_image_url, "").in_(("",))
        | Follower.profile_image_url.contains(DEFAULT_AVATAR_MARKER),
        "no_bio": func.btrim(func.coalesce(Follower.description, "")).in_(("",)),
    }


_REASON_WEIGHT = {
    "young": SCORE_YOUNG,
    "fresh_follow": SCORE_FRESH_FOLLOW,
    "no_avatar": SCORE_NO_AVATAR,
    "no_bio": SCORE_NO_BIO,
}


def suspicious_followers(
    db: Session, channel_id: int, now: datetime | None = None
) -> list[SuspiciousFollower]:
    """Followers whose profile looks bot-like. Only enriched rows can be scored
    (account age/avatar/bio come from Helix).

    Note what this cannot see: it judges each follower on their own, so a batch of
    accounts created together and aged before use passes every check. That is what
    `base_age_concentration` is for.
    """
    reference = now if now is not None else datetime.now(UTC)
    flags = _reason_flags(reference)
    score = sum(
        case((flag, _REASON_WEIGHT[reason]), else_=0) for reason, flag in flags.items()
    )
    rows = db.execute(
        select(
            Follower.login,
            Follower.display_name,
            score.label("score"),
            *[flag.label(reason) for reason, flag in flags.items()],
        )
        .where(Follower.channel_id == channel_id)
        .where(Follower.enriched_at.is_not(None))
        .where(score >= SUSPICIOUS_THRESHOLD)
        .order_by(score.desc())
        .limit(SUSPICIOUS_LIMIT)
    ).all()
    return [
        SuspiciousFollower(
            login=row.login,
            display_name=row.display_name,
            score=row.score,
            reasons=[reason for reason in flags if getattr(row, reason)],
        )
        for row in rows
    ]


def follow_velocity(db: Session, channel_id: int) -> list[VelocityDay]:
    """Daily follow counts (from followed_at) with spikes flagged where a day
    exceeds mean + K*stdev: viral moments or bot bursts stand out."""
    day = func.date(Follower.followed_at)
    per_day = {
        row.day.strftime("%Y-%m-%d"): row.follows
        for row in db.execute(
            select(day.label("day"), func.count().label("follows"))
            .where(Follower.channel_id == channel_id)
            .group_by(day)
        )
    }
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
    # Join on Stream: an Insight only knows its stream, so without this the
    # topics come from every channel on the platform and a follow of yours gets
    # credited to whatever someone else happened to be talking about at that
    # minute. Measured in production before the join existed: three of these,
    # including another streamer's live titled "Falas incoerentes e confusao"
    # showing up as what earned a follow.
    topics = list(
        db.scalars(
            select(Insight)
            .join(Stream, Stream.id == Insight.stream_id)
            .where(Stream.channel_id == channel_id)
            .where(Insight.type == InsightType.TOPIC)
        )
    )
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
