"""Opens a stream row for a live whose stream.online webhook never arrived.

The webhook is the only thing that starts a capture. When the API is down, or
the callback fails, as a streamer goes live, no capture worker ever sees that
live. Each capture worker asks Helix once a minute which signed-up channels are
on air and opens the row itself; start_stream makes the webhook, this check and
the other worker's check all land on one row.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db import session_factory
from core.models import Channel, Stream
from core.streams import start_stream
from core.twitch import LiveStream, TwitchAuthError

CHECK_INTERVAL_SECONDS = 60.0
# Helix and the webhook report the same start time, give or take clock skew. A
# stream row that started this close to Helix's start is that same live, even
# if stream.offline already closed it and Helix still lists it for a minute.
SAME_LIVE_TOLERANCE = timedelta(minutes=2)


class LiveChannels(Protocol):
    def live(self, user_ids: list[int]) -> list[LiveStream]: ...


class MissedLiveFinder:
    _log = logging.getLogger(__name__)

    def __init__(self, helix: LiveChannels) -> None:
        self._helix = helix

    async def watch_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.check_once)
            except (TwitchAuthError, httpx.HTTPError):
                self._log.exception("helix live check failed, retrying next minute")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def check_once(self) -> None:
        with session_factory()() as db:
            self.open_missed(db)
            db.commit()

    def open_missed(self, db: Session) -> list[Stream]:
        channels = {channel.twitch_user_id: channel for channel in db.scalars(select(Channel))}
        on_air = self._helix.live(list(channels))
        latest = self._latest_starts(db, [channels[int(live.user_id)].id for live in on_air])
        opened: list[Stream] = []
        for live in on_air:
            channel = channels[int(live.user_id)]
            if channel.id in latest and latest[channel.id] >= live.started_at - SAME_LIVE_TOLERANCE:
                continue
            opened.append(start_stream(db, channel, live.started_at))
            self._log.info(
                "live opened from Helix (stream.online webhook missed)",
                extra={"channel_id": channel.id},
            )
        return opened

    def _latest_starts(self, db: Session, channel_ids: list[int]) -> dict[int, datetime]:
        rows = db.execute(
            select(Stream.channel_id, func.max(Stream.started_at))
            .where(Stream.channel_id.in_(channel_ids))
            .group_by(Stream.channel_id)
        )
        return {channel_id: started_at for channel_id, started_at in rows}
