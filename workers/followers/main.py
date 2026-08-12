"""Follower sync worker: walks each channel's follower list on its own schedule.

A process of its own rather than a job on the shared queue, because that queue is
built around streams: `Job.stream_id` is required and the whole state machine in
core.worker_loop drives a stream's status. Bending it to carry channel-level work
would mean editing the path transcribe and analyze depend on, which is not a
trade worth making to fetch followers.

It is also deliberately not folded into the capture worker: a follower walk takes
minutes, and nothing about it may ever delay picking up a live.

The backoff below is not decoration. The first version of this loop counted a
failed channel as progress and re-selected it immediately, because a channel that
fails keeps the null `followers_synced_at` that made it due. In production on
2026-08-12 that turned one channel with a dead refresh token into roughly two
requests a second against Twitch's token endpoint, for as long as it ran.
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
# How long a channel that just failed is left alone. A dead refresh token only
# clears when its owner signs in again, and that clears followers_synced_at, which
# puts the channel back at the front of the queue immediately. So this only paces
# the pointless retries in between.
FAILURE_COOLDOWN_SECONDS = 900.0


def attemptable(
    due: list[Channel], cooling_off: dict[int, float], now: float
) -> list[Channel]:
    """Of the channels the database says are due, the ones not cooling off.

    Separate from the loop so the rule can be tested: `channels_due` keeps
    returning a failed channel, because failing is exactly what leaves it due.
    """
    return [channel for channel in due if now >= cooling_off.get(channel.id, 0.0)]


def main() -> None:
    setup_logging()
    logger.info("follower sync worker starting")
    factory = session_factory()
    # channel id -> when it may be tried again. In memory on purpose: a restart
    # earning one retry per channel is the behaviour we want.
    cooling_off: dict[int, float] = {}
    while True:
        progressed = False
        with factory() as db:
            due = channels_due(db, datetime.now(UTC))
            for channel in attemptable(due, cooling_off, time.monotonic()):
                if _sync_one(db, channel):
                    cooling_off.pop(channel.id, None)
                    progressed = True
                else:
                    cooling_off[channel.id] = (
                        time.monotonic() + FAILURE_COOLDOWN_SECONDS
                    )
        # Only a completed pass counts as progress. Sleeping whenever nothing
        # completed is what stops a permanently failing channel from spinning.
        if not progressed:
            time.sleep(IDLE_SLEEP_SECONDS)


def _sync_one(db: Session, channel: Channel) -> bool:
    """Run one channel's pass. Returns whether it finished.

    An unfinished pass is normal and resumable: the cursor is stored, so the next
    attempt picks up mid-walk. A channel that blows up must not take the worker
    down with it either, or one bad token stops every other channel from syncing.
    """
    try:
        return sync_channel(db, channel).completed
    except Exception:  # noqa: BLE001 - one channel must never kill the loop
        db.rollback()
        logger.exception("follower sync failed", extra={"channel_id": channel.id})
        return False


if __name__ == "__main__":
    main()
