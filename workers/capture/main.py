"""Capture worker: polls for active streams and runs one CaptureSession each.

DB polling (not pub/sub) keeps the worker stateless and restart-safe: on boot
it picks up any stream still marked capturing.
"""

import asyncio
import logging

from sqlalchemy import select

from core.db import session_factory
from core.logging_setup import setup_logging
from core.models import Channel, Stream, StreamStatus
from workers.capture.live_sessions import LiveSessions

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
    sessions = LiveSessions({})
    factory = session_factory()
    while True:
        rows = await asyncio.to_thread(_load_capturing_streams)
        for session in sessions.open_new(rows):
            session.start()
        for session in sessions.closing(rows):
            await session.stop_and_finalize(factory)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    setup_logging()
    logger.info("capture worker starting")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
