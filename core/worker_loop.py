"""Shared job-worker loop: picks queued jobs by next-live urgency, drives the
job/stream state machine and retries. Used by transcribe and analyze workers.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import session_factory
from core.heartbeat import start_heartbeat
from core.models import Channel, Job, JobStatus, Stream, StreamStatus
from core.queues import enqueue_job, get_valkey
from core.schedule import HISTORY_LIMIT, estimate_next_live

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5.0
MAX_ATTEMPTS = 3

JobHandler = Callable[[Session, Stream], object]


@dataclass(frozen=True)
class WorkerSpec:
    job_type: str
    running_status: StreamStatus
    done_status: StreamStatus
    next_job_type: str | None = None


def _queued_jobs(db: Session, job_type: str) -> list[tuple[Job, Stream, Channel]]:
    rows = db.execute(
        select(Job, Stream, Channel)
        .join(Stream, Job.stream_id == Stream.id)
        .join(Channel, Stream.channel_id == Channel.id)
        .where(Job.type == job_type)
        .where(Job.status == JobStatus.QUEUED)
    ).all()
    return [(job, stream, channel) for job, stream, channel in rows]


def _channel_history(db: Session, channel_id: int) -> list[datetime]:
    return list(
        db.scalars(
            select(Stream.started_at)
            .where(Stream.channel_id == channel_id)
            .order_by(Stream.started_at.desc())
            .limit(HISTORY_LIMIT)
        )
    )


def pick_next_job(db: Session, job_type: str, now: datetime) -> Job | None:
    """Most urgent queued job: smallest (estimated next live - now).
    This enforces the PRD rule that reports finish before the next live."""
    candidates = _queued_jobs(db, job_type)
    if not candidates:
        return None

    def urgency(item: tuple[Job, Stream, Channel]) -> datetime:
        _, _, channel = item
        return estimate_next_live(now, _channel_history(db, channel.id))

    job, stream, channel = min(candidates, key=urgency)
    logger.info(
        "job picked (next live estimated %s)",
        urgency((job, stream, channel)).isoformat(),
        extra={"stream_id": stream.id, "channel_id": channel.id, "job_type": job_type},
    )
    return job


def _run_job(db: Session, spec: WorkerSpec, job: Job, handler: JobHandler) -> None:
    stream = db.get(Stream, job.stream_id)
    if stream is None:
        job.status = JobStatus.FAILED
        job.error = f"stream {job.stream_id} not found"
        db.commit()
        return
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    stream.status = spec.running_status
    db.commit()

    try:
        result = handler(db, stream)
    except Exception as err:  # any failure: retry up to MAX_ATTEMPTS, then fail
        db.rollback()
        _register_failure(db, spec, job, err)
        return

    job.status = JobStatus.DONE
    job.finished_at = datetime.now(UTC)
    stream.status = spec.done_status
    if spec.next_job_type is not None:
        enqueue_job(db, get_valkey(), spec.next_job_type, stream.id)
    db.commit()
    logger.info(
        "%s done: %s",
        spec.job_type,
        result,
        extra={"stream_id": stream.id, "job_type": spec.job_type},
    )


def _register_failure(db: Session, spec: WorkerSpec, job: Job, err: Exception) -> None:
    stream = db.get(Stream, job.stream_id)
    if stream is None:
        return
    job.error = f"{type(err).__name__}: {err}"
    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        stream.status = StreamStatus.FAILED
        logger.error(
            "%s failed permanently: %s",
            spec.job_type,
            job.error,
            extra={"stream_id": stream.id, "job_type": spec.job_type},
        )
    else:
        job.status = JobStatus.QUEUED
        logger.warning(
            "%s attempt %d failed, requeued: %s",
            spec.job_type,
            job.attempts,
            job.error,
            extra={"stream_id": stream.id, "job_type": spec.job_type},
        )
    db.commit()


def run_worker(spec: WorkerSpec, handler: JobHandler) -> None:
    start_heartbeat(spec.job_type)
    factory = session_factory()
    while True:
        with factory() as db:
            job = pick_next_job(db, spec.job_type, datetime.now(UTC))
            if job is not None:
                _run_job(db, spec, job, handler)
                continue
        time.sleep(POLL_INTERVAL_SECONDS)
