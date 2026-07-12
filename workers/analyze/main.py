"""Analysis worker: SQL peaks + local LLM insights over the priority queue."""

import logging

from sqlalchemy.orm import Session

from core.llm import get_llm_backend
from core.logging_setup import setup_logging
from core.models import Stream, StreamStatus
from core.queues import JOB_ANALYZE
from core.worker_loop import WorkerSpec, run_worker
from workers.analyze.pipeline import run_analysis

logger = logging.getLogger(__name__)

SPEC = WorkerSpec(
    job_type=JOB_ANALYZE,
    running_status=StreamStatus.ANALYZING,
    done_status=StreamStatus.READY,
)


def main() -> None:
    setup_logging()
    logger.info("analyze worker starting")
    backend = get_llm_backend()

    def handle(db: Session, stream: Stream) -> object:
        return run_analysis(db, stream, backend)

    run_worker(SPEC, handle)


if __name__ == "__main__":
    main()
