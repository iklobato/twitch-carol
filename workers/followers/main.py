"""Follower sync worker: walks each channel's follower list on its own schedule.

A process of its own rather than a job on the shared queue, because that queue is
built around streams: `Job.stream_id` is required and the whole state machine in
core.worker_loop drives a stream's status. Bending it to carry channel-level work
would mean editing the path transcribe and analyze depend on, which is not a
trade worth making to fetch followers.

It is also deliberately not folded into the capture worker: a follower walk takes
minutes, and nothing about it may ever delay picking up a live.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.db import session_factory
from core.follower_sync import channels_due, sync_channel
from core.logging_setup import setup_logging
from core.models import Channel

logger = logging.getLogger(__name__)

IDLE_SLEEP_SECONDS = 60.0


def main() -> None:
    setup_logging()
    logger.info("follower sync worker starting")
    factory = session_factory()
    while True:
        synced = 0
        with factory() as db:
            # An interrupted channel keeps its stored cursor, so the next round
            # picks it up where it stopped rather than starving it.
            for channel in channels_due(db, datetime.now(UTC)):
                _sync_one(db, channel)
                synced += 1
        if synced == 0:
            time.sleep(IDLE_SLEEP_SECONDS)


def _sync_one(db: Session, channel: Channel) -> None:
    """One channel's pass. A channel that blows up must not take the worker down
    with it, or one bad token stops every other channel from ever syncing."""
    try:
        sync_channel(db, channel)
    except Exception:  # noqa: BLE001 - one channel must never kill the loop
        db.rollback()
        logger.exception("follower sync failed", extra={"channel_id": channel.id})


if __name__ == "__main__":
    main()
