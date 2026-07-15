"""Data factories for DB-backed tests. All timestamps are UTC and recent so
the current-month chat partition (created by the pg fixtures) covers them."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from core.models import (
    BitsLeader,
    Channel,
    ChatMessage,
    Event,
    Follower,
    Goal,
    Insight,
    InsightType,
    Job,
    JobStatus,
    PastBroadcast,
    Peak,
    SegmentKind,
    Stream,
    StreamStatus,
    Subscription,
    TranscriptSegment,
    ViewerSample,
    Vip,
)

_sequence = iter(range(1000, 10_000_000))


def add_follower(
    db: Session,
    channel: Channel,
    login: str,
    followed_minutes_ago: int = 60,
    broadcaster_type: str | None = None,
    account_created_at: datetime | None = None,
    enriched: bool = False,
    followed_at: datetime | None = None,
) -> Follower:
    unique = next(_sequence)
    if followed_at is None:
        followed_at = datetime.now(UTC) - timedelta(minutes=followed_minutes_ago)
    follower = Follower(
        channel_id=channel.id,
        twitch_user_id=unique,
        login=login,
        followed_at=followed_at,
        display_name=login.title() if enriched else None,
        profile_image_url=f"https://cdn/{login}.png" if enriched else None,
        broadcaster_type=broadcaster_type,
        account_created_at=account_created_at,
        enriched_at=followed_at if enriched else None,
    )
    db.add(follower)
    db.flush()
    return follower


def add_vip(db: Session, channel: Channel, login: str) -> Vip:
    unique = next(_sequence)
    vip = Vip(channel_id=channel.id, twitch_user_id=unique, login=login)
    db.add(vip)
    db.flush()
    return vip


def add_goal(
    db: Session,
    channel: Channel,
    goal_type: str = "follower",
    current_amount: int = 500,
    target_amount: int = 1000,
    description: str | None = "Meta de seguidores",
    created_at: datetime | None = None,
) -> Goal:
    unique = next(_sequence)
    goal = Goal(
        channel_id=channel.id,
        twitch_goal_id=str(unique),
        goal_type=goal_type,
        description=description,
        current_amount=current_amount,
        target_amount=target_amount,
        created_at=created_at,
    )
    db.add(goal)
    db.flush()
    return goal


def add_subscription(
    db: Session,
    channel: Channel,
    login: str,
    tier: str = "1000",
    is_gift: bool = False,
    gifter_login: str | None = None,
) -> Subscription:
    unique = next(_sequence)
    sub = Subscription(
        channel_id=channel.id,
        twitch_user_id=unique,
        login=login,
        tier=tier,
        is_gift=is_gift,
        gifter_login=gifter_login,
    )
    db.add(sub)
    db.flush()
    return sub


def add_bits_leader(
    db: Session, channel: Channel, login: str, rank: int, score: int
) -> BitsLeader:
    leader = BitsLeader(channel_id=channel.id, login=login, rank=rank, score=score)
    db.add(leader)
    db.flush()
    return leader


def add_past_broadcast(
    db: Session,
    channel: Channel,
    title: str = "Live antiga",
    published_minutes_ago: int = 1440,
    duration_seconds: int = 3600,
    view_count: int = 100,
) -> PastBroadcast:
    unique = next(_sequence)
    broadcast = PastBroadcast(
        channel_id=channel.id,
        twitch_video_id=str(unique),
        title=title,
        published_at=datetime.now(UTC) - timedelta(minutes=published_minutes_ago),
        duration_seconds=duration_seconds,
        view_count=view_count,
        url=f"https://twitch.tv/videos/{unique}",
    )
    db.add(broadcast)
    db.flush()
    return broadcast


def make_channel(db: Session, login: str | None = None) -> Channel:
    unique = next(_sequence)
    channel = Channel(
        twitch_user_id=unique,
        login=login or f"tester_{unique}",
        display_name=f"Tester {unique}",
        scopes=["bits:read"],
    )
    db.add(channel)
    db.flush()
    return channel


def make_stream(
    db: Session,
    channel: Channel,
    status: StreamStatus = StreamStatus.READY,
    started_minutes_ago: int = 60,
    duration_minutes: int | None = 30,
    title: str | None = None,
    category: str | None = None,
) -> Stream:
    started = datetime.now(UTC) - timedelta(minutes=started_minutes_ago)
    stream = Stream(
        channel_id=channel.id,
        started_at=started,
        ended_at=(
            started + timedelta(minutes=duration_minutes) if duration_minutes else None
        ),
        status=status,
        title=title,
        category=category,
    )
    db.add(stream)
    db.flush()
    return stream


def add_chat(
    db: Session,
    stream: Stream,
    count: int,
    offset_seconds: int = 0,
    author: str | None = None,
    text: str = "mensagem de teste",
    spread_seconds: int = 60,
    badges: dict | None = None,
) -> list[ChatMessage]:
    messages = []
    for index in range(count):
        message = ChatMessage(
            stream_id=stream.id,
            channel_id=stream.channel_id,
            sent_at=stream.started_at
            + timedelta(
                seconds=offset_seconds + (index * spread_seconds) / max(count, 1)
            ),
            message_id=str(uuid.uuid4()),
            author_id=author or f"author_{index % 7}",
            author_login=author or f"author_{index % 7}",
            text=text,
            badges=badges,
        )
        db.add(message)
        messages.append(message)
    db.flush()
    return messages


def add_segment(
    db: Session,
    stream: Stream,
    offset_seconds: int,
    text: str | None = "fala de teste sobre programação",
    kind: SegmentKind = SegmentKind.SPEECH,
    duration_seconds: int = 20,
) -> TranscriptSegment:
    segment = TranscriptSegment(
        stream_id=stream.id,
        started_at=stream.started_at + timedelta(seconds=offset_seconds),
        ended_at=stream.started_at
        + timedelta(seconds=offset_seconds + duration_seconds),
        kind=kind,
        text=text,
    )
    db.add(segment)
    db.flush()
    return segment


def add_event(
    db: Session,
    stream: Stream,
    event_type: str = "channel.follow",
    offset_seconds: int = 30,
    amount: int | None = None,
    login: str | None = None,
    payload: dict | None = None,
) -> Event:
    body = payload if payload is not None else {"mock": True}
    if login is not None:
        body = {**body, "user_login": login}
    event = Event(
        stream_id=stream.id,
        channel_id=stream.channel_id,
        occurred_at=stream.started_at + timedelta(seconds=offset_seconds),
        type=event_type,
        payload=body,
        amount=amount,
    )
    db.add(event)
    db.flush()
    return event


def add_viewer_samples(db: Session, stream: Stream, counts: list[int]) -> None:
    for minute, count in enumerate(counts):
        db.add(
            ViewerSample(
                stream_id=stream.id,
                sampled_at=stream.started_at + timedelta(minutes=minute),
                viewer_count=count,
            )
        )
    db.flush()


def add_peak(
    db: Session, stream: Stream, offset_seconds: int = 60, score: float = 3.0
) -> Peak:
    peak = Peak(
        stream_id=stream.id,
        window_start=stream.started_at + timedelta(seconds=offset_seconds),
        window_end=stream.started_at + timedelta(seconds=offset_seconds + 60),
        metric="chat_rate",
        score=score,
    )
    db.add(peak)
    db.flush()
    return peak


def add_insight(
    db: Session,
    stream: Stream,
    insight_type: InsightType = InsightType.SUMMARY,
    content: str = "Resumo de teste.",
    evidence: dict | None = None,
) -> Insight:
    insight = Insight(
        stream_id=stream.id,
        type=insight_type,
        content=content,
        evidence=evidence or {"message_ids": [], "segment_ids": []},
        model_used="fake",
        tokens_in=10,
        tokens_out=5,
    )
    db.add(insight)
    db.flush()
    return insight


def add_job(
    db: Session,
    stream: Stream,
    job_type: str,
    status: JobStatus = JobStatus.QUEUED,
    started_minutes_ago: int | None = None,
    finished_minutes_ago: int | None = None,
) -> Job:
    now = datetime.now(UTC)
    job = Job(
        type=job_type,
        stream_id=stream.id,
        status=status,
        attempts=0 if status == JobStatus.QUEUED else 1,
        started_at=(
            now - timedelta(minutes=started_minutes_ago)
            if started_minutes_ago
            else None
        ),
        finished_at=(
            now - timedelta(minutes=finished_minutes_ago)
            if finished_minutes_ago
            else None
        ),
    )
    db.add(job)
    db.flush()
    return job
