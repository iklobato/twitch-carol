"""Transcription worker: VAD + faster-whisper over the priority queue.

The jobs table is the ordering source (Valkey streams are FIFO and cannot
reprioritize); the jobs:transcribe stream stays as an observability signal.
"""

import logging

from sqlalchemy.orm import Session

from core.logging_setup import setup_logging
from core.models import Stream, StreamStatus
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE
from core.worker_loop import WorkerSpec, run_worker
from workers.transcribe.pipeline import Transcriber, process_stream

logger = logging.getLogger(__name__)

SPEC = WorkerSpec(
    job_type=JOB_TRANSCRIBE,
    running_status=StreamStatus.TRANSCRIBING,
    done_status=StreamStatus.QUEUED_ANALYSIS,
    next_job_type=JOB_ANALYZE,
)


def main() -> None:
    setup_logging()
    logger.info("transcribe worker starting")
    transcriber = Transcriber()

    def handle(db: Session, stream: Stream) -> object:
        return process_stream(db, stream, transcriber)

    run_worker(SPEC, handle)


if __name__ == "__main__":
    main()
