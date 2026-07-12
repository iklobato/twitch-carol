"""SQL-computed stream metrics. Product rule 2: every number shown in the UI
comes from here (SQL), never from LLM text."""

from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from core.models import ChatMessage, Event, Stream, StreamStatus, ViewerSample

BUCKET_SECONDS = 60
COMPARISON_WINDOW = 10


def chat_rate_buckets(db: Session, stream_id: int) -> list[tuple[datetime, int]]:
    bucket = func.date_bin(
        timedelta(seconds=BUCKET_SECONDS), ChatMessage.sent_at, datetime(2000, 1, 1)
    ).label("bucket")
    rows = db.execute(
        select(bucket, func.count())
        .where(ChatMessage.stream_id == stream_id)
        .group_by(bucket)
        .order_by(bucket)
    ).all()
    return [(row[0], row[1]) for row in rows]


def stream_numbers(db: Session, stream: Stream) -> dict[str, float]:
    messages, chatters = db.execute(
        select(func.count(), func.count(func.distinct(ChatMessage.author_id))).where(
            ChatMessage.stream_id == stream.id
        )
    ).one()
    peak_viewers, avg_viewers = db.execute(
        select(
            func.coalesce(func.max(ViewerSample.viewer_count), 0),
            func.coalesce(func.avg(ViewerSample.viewer_count), 0),
        ).where(ViewerSample.stream_id == stream.id)
    ).one()
    events = (
        db.scalar(
            select(func.count()).select_from(Event).where(Event.stream_id == stream.id)
        )
        or 0
    )
    ended_at = stream.ended_at if stream.ended_at is not None else stream.started_at
    return {
        "duration_minutes": round(
            (ended_at - stream.started_at).total_seconds() / 60, 1
        ),
        "messages": float(messages),
        "chatters": float(chatters),
        "peak_viewers": float(peak_viewers),
        "avg_viewers": round(float(avg_viewers), 1),
        "events": float(events),
    }


def previous_streams_average(db: Session, stream: Stream) -> dict[str, float] | None:
    """Mean of each metric over the channel's previous COMPARISON_WINDOW
    finished lives (the PRD's "comparativo das últimas 10")."""
    previous = db.scalars(
        select(Stream)
        .where(Stream.channel_id == stream.channel_id)
        .where(Stream.id != stream.id)
        .where(Stream.started_at < stream.started_at)
        .where(Stream.status == StreamStatus.READY)
        .order_by(Stream.started_at.desc())
        .limit(COMPARISON_WINDOW)
    ).all()
    if not previous:
        return None
    per_stream = [stream_numbers(db, s) for s in previous]
    return {
        key: round(mean(numbers[key] for numbers in per_stream), 1)
        for key in per_stream[0]
    }


def average_job_seconds(db: Session, job_type: str) -> float | None:
    """Measured mean duration of finished jobs; grounds the queue ETA in
    real history instead of a guess."""
    from core.models import Job, JobStatus

    seconds = db.scalar(
        select(
            func.avg(
                func.extract("epoch", Job.finished_at - Job.started_at).cast(Integer)
            )
        )
        .where(Job.type == job_type)
        .where(Job.status == JobStatus.DONE)
        .where(Job.finished_at.is_not(None))
    )
    return float(seconds) if seconds is not None else None
