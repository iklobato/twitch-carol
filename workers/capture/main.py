"""Capture worker: polls for active streams and runs one CaptureSession each.

DB polling (not pub/sub) keeps the worker stateless and restart-safe: on boot
it picks up any stream still marked capturing.
"""

import asyncio
import logging

from sqlalchemy import select

from core.db import session_factory
from core.heartbeat import start_heartbeat
from core.logging_setup import setup_logging
from core.models import Channel, Stream, StreamStatus
from workers.capture.session import CaptureSession

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 3.0


def _load_capturing_streams() -> list[tuple[Stream, Channel]]:
    with session_factory()() as db:
        rows = db.execute(
            select(Stream, Channel)
            .join(Channel, Stream.channel_id == Channel.id)
            .where(Stream.status == StreamStatus.CAPTURING)
        ).all()
        return [(stream, channel) for stream, channel in rows]


async def run_forever() -> None:
    sessions: dict[int, CaptureSession] = {}
    factory = session_factory()
    while True:
        rows = await asyncio.to_thread(_load_capturing_streams)
        live = {stream.id for stream, _ in rows if stream.ended_at is None}
        ended = [
            (stream, channel) for stream, channel in rows if stream.ended_at is not None
        ]

        for stream, channel in rows:
            if stream.id in live and stream.id not in sessions:
                session = CaptureSession(stream, channel)
                sessions[stream.id] = session
                session.start()

        for stream, channel in ended:
            if stream.id in sessions:
                session = sessions.pop(stream.id)
            else:
                # Worker restarted mid-live: no collector stats, audit from DB only.
                session = CaptureSession(stream, channel)
            await session.stop_and_finalize(factory)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    setup_logging()
    logger.info("capture worker starting")
    start_heartbeat("capture")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
