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
