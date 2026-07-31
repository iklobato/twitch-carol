"""Job queues over Valkey streams, mirrored in the jobs table for observability."""

import logging
from collections.abc import Sequence
from functools import lru_cache

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Job, JobStatus, Stream, StreamStatus

logger = logging.getLogger(__name__)

JOB_TRANSCRIBE = "transcribe"
JOB_ANALYZE = "analyze"
QUEUE_KEYS = {
    JOB_TRANSCRIBE: "jobs:transcribe",
    JOB_ANALYZE: "jobs:analyze",
}
REQUEUE_STATUS = {
    JOB_TRANSCRIBE: StreamStatus.QUEUED_TRANSCRIPTION,
    JOB_ANALYZE: StreamStatus.QUEUED_ANALYSIS,
}


@lru_cache
def get_valkey() -> redis.Redis:
    return redis.Redis.from_url(get_settings().valkey_url, decode_responses=True)


def enqueue_job(db: Session, job_type: str, stream_id: int) -> Job:
    """The jobs table IS the queue: workers poll it (see core.worker_loop).

    There used to be a mirrored xadd to a Valkey stream here, kept "for
    observability", but nothing ever read it: no consumer, and the Grafana
    panels query this table. It was the last thing making production depend on
    Valkey, so it is gone. QUEUE_KEYS stays for the local simulation harness.
    """
    job = Job(type=job_type, stream_id=stream_id, status=JobStatus.QUEUED)
    db.add(job)
    db.flush()
    logger.info("job enqueued", extra={"stream_id": stream_id, "job_type": job_type})
    return job


def _failed_step(db: Session, stream_id: int) -> str | None:
    """Job type of the newest failed job: the step to restart from. A stream
    that died in analyze must not restart at transcribe, which would re-run
    (and re-pay for) transcription that already succeeded."""
    return db.scalars(
        select(Job.type)
        .where(Job.stream_id == stream_id)
        .where(Job.status == JobStatus.FAILED)
        .order_by(Job.id.desc())
        .limit(1)
    ).first()


def _is_pending(db: Session, stream_id: int, job_type: str) -> bool:
    return (
        db.scalars(
            select(Job.id)
            .where(Job.stream_id == stream_id)
            .where(Job.type == job_type)
            .where(Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)))
            .limit(1)
        ).first()
        is not None
    )


def requeue_failed_streams(
    db: Session, stream_ids: Sequence[int] | None = None
) -> list[tuple[int, str]]:
    """Puts FAILED streams back on the queue at the step that failed, for when
    the cause was an outage rather than the data (an expired key, an API out of
    credit). Both pipelines wipe their own rows before rewriting them, so a
    rerun replaces the previous result instead of duplicating it.

    Skips a stream that already has the same job queued or running, so running
    this twice never pays for the same transcription twice.

    Returns the (stream_id, job_type) pairs requeued. The caller commits.
    """
    query = select(Stream).where(Stream.status == StreamStatus.FAILED)
    if stream_ids is not None:
        query = query.where(Stream.id.in_(stream_ids))

    requeued: list[tuple[int, str]] = []
    for stream in db.scalars(query.order_by(Stream.id)):
        job_type = _failed_step(db, stream.id)
        if job_type not in REQUEUE_STATUS or _is_pending(db, stream.id, job_type):
            continue
        stream.status = REQUEUE_STATUS[job_type]
        enqueue_job(db, job_type, stream.id)
        requeued.append((stream.id, job_type))
    return requeued
