"""Job queues over Valkey streams, mirrored in the jobs table for observability."""

import logging
from functools import lru_cache

import redis
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Job, JobStatus

logger = logging.getLogger(__name__)

JOB_TRANSCRIBE = "transcribe"
JOB_ANALYZE = "analyze"
QUEUE_KEYS = {
    JOB_TRANSCRIBE: "jobs:transcribe",
    JOB_ANALYZE: "jobs:analyze",
}


@lru_cache
def get_valkey() -> redis.Redis:
    return redis.Redis.from_url(get_settings().valkey_url, decode_responses=True)


def enqueue_job(db: Session, valkey: redis.Redis, job_type: str, stream_id: int) -> Job:
    job = Job(type=job_type, stream_id=stream_id, status=JobStatus.QUEUED)
    db.add(job)
    db.flush()
    valkey.xadd(
        QUEUE_KEYS[job_type], {"job_id": str(job.id), "stream_id": str(stream_id)}
    )
    logger.info("job enqueued", extra={"stream_id": stream_id, "job_type": job_type})
    return job
