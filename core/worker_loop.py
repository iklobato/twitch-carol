"""Shared job-worker loop: picks queued jobs by next-live urgency, drives the
job/stream state machine and retries. Used by transcribe and analyze workers.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from core.db import session_factory
from core.models import Channel, Job, JobStatus, Stream, StreamStatus
from core.queues import enqueue_job
from core.schedule import HISTORY_LIMIT, estimate_next_live

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5.0
MAX_ATTEMPTS = 3
HEARTBEAT_INTERVAL_SECONDS = 30.0
# Ten missed beats. Deliberately unrelated to how long a job legitimately takes
# (a transcribe of a long live runs 90+ min): a duration timeout would have to
# guess that ceiling and would kill real work when it guessed low. A stopped
# heartbeat means the process is gone, whatever the job was doing.
HEARTBEAT_STALE_AFTER = timedelta(minutes=5)

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


class _Heartbeat:
    """Beats `last_heartbeat` while the handler runs, from its own session (the
    handler owns the caller's). Missing a beat is never fatal: the reclaim only
    acts after HEARTBEAT_STALE_AFTER, so a blip is covered by the next beat.
    """

    def __init__(self, job_id: int) -> None:
        self._job_id = job_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _beat(self) -> None:
        factory = session_factory()
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                with factory() as db:
                    db.execute(
                        update(Job)
                        .where(Job.id == self._job_id)
                        .values(last_heartbeat=datetime.now(UTC))
                    )
                    db.commit()
            except Exception:  # noqa: BLE001 - a lost beat must never kill the job
                logger.warning(
                    "heartbeat failed", extra={"job_id": self._job_id}, exc_info=True
                )


def reclaim_dead_jobs(db: Session, job_type: str, now: datetime) -> list[Job]:
    """Requeue jobs whose worker died mid-run (crash, OOM, redeploy).

    Nothing else ever picks these up: _queued_jobs only looks at QUEUED, so the
    job and its stream sit in a non-terminal state forever. Rows written before
    the heartbeat existed have no beat at all, so fall back to started_at.
    """
    cutoff = now - HEARTBEAT_STALE_AFTER
    dead = list(
        db.scalars(
            select(Job)
            .where(Job.type == job_type)
            .where(Job.status == JobStatus.RUNNING)
            .where(
                or_(
                    Job.last_heartbeat < cutoff,
                    and_(Job.last_heartbeat.is_(None), Job.started_at < cutoff),
                )
            )
        )
    )
    for job in dead:
        # attempts was already incremented when it started, so a job that keeps
        # killing its worker fails for good instead of looping forever.
        if job.attempts >= MAX_ATTEMPTS:
            job.status = JobStatus.FAILED
            job.finished_at = now
            job.error = "worker died mid-job (heartbeat stopped) too many times"
            stream = db.get(Stream, job.stream_id)
            if stream is not None:
                stream.status = StreamStatus.FAILED
            logger.error(
                "%s job %d abandoned: worker died %d times",
                job_type,
                job.id,
                job.attempts,
                extra={"stream_id": job.stream_id, "job_type": job_type},
            )
        else:
            job.status = JobStatus.QUEUED
            job.error = "worker died mid-job (heartbeat stopped); requeued"
            logger.warning(
                "%s job %d requeued: worker died mid-run (attempt %d)",
                job_type,
                job.id,
                job.attempts,
                extra={"stream_id": job.stream_id, "job_type": job_type},
            )
    if dead:
        db.commit()
    return dead


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
    job.last_heartbeat = job.started_at
    stream.status = spec.running_status
    db.commit()

    try:
        with _Heartbeat(job.id):
            result = handler(db, stream)
    except Exception as err:  # any failure: retry up to MAX_ATTEMPTS, then fail
        db.rollback()
        _register_failure(db, spec, job, err)
        return

    job.status = JobStatus.DONE
    job.finished_at = datetime.now(UTC)
    stream.status = spec.done_status
    if spec.next_job_type is not None:
        enqueue_job(db, spec.next_job_type, stream.id)
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
    factory = session_factory()
    while True:
        with factory() as db:
            now = datetime.now(UTC)
            reclaim_dead_jobs(db, spec.job_type, now)
            job = pick_next_job(db, spec.job_type, now)
            if job is not None:
                _run_job(db, spec, job, handler)
                continue
        time.sleep(POLL_INTERVAL_SECONDS)
