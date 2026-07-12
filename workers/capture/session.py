"""A CaptureSession owns the three collectors of one live stream and, once the
stream ends, writes the completeness audit and enqueues transcription."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from core.models import Channel, Event, Stream, StreamStatus
from core.queues import JOB_TRANSCRIBE, enqueue_job, get_valkey
from workers.capture.collectors import (
    VIEWER_SAMPLE_INTERVAL_SECONDS,
    AudioRecorder,
    ChatCollector,
    ViewerSampler,
)

logger = logging.getLogger(__name__)


class CaptureSession:
    def __init__(self, stream: Stream, channel: Channel) -> None:
        self.stream_id = stream.id
        self._channel_id = channel.id
        self._chat = ChatCollector(stream, channel)
        self._viewers = ViewerSampler(stream, channel)
        self._audio = AudioRecorder(stream, channel)
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        logger.info(
            "capture session started",
            extra={"stream_id": self.stream_id, "channel_id": self._channel_id},
        )

    async def _run(self) -> None:
        await asyncio.gather(
            self._chat.run(self._stop),
            self._viewers.run(self._stop),
            self._audio.run(self._stop),
            return_exceptions=True,
        )

    async def stop_and_finalize(self, db_session_factory) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
        await asyncio.to_thread(self._finalize, db_session_factory)

    def _finalize(self, db_session_factory) -> None:
        with db_session_factory() as db:
            stream = db.get(Stream, self.stream_id)
            if stream is None:
                return
            stream.audit = build_audit(
                db, stream, self._chat.stats, self._viewers.stats, self._audio.stats
            )
            stream.status = StreamStatus.QUEUED_TRANSCRIPTION
            enqueue_job(db, get_valkey(), JOB_TRANSCRIBE, stream.id)
            db.commit()
        logger.info(
            "capture session finalized",
            extra={"stream_id": self.stream_id, "channel_id": self._channel_id},
        )


def build_audit(
    db, stream: Stream, chat_stats: dict, viewer_stats: dict, audio_stats: dict
) -> dict:
    ended_at = stream.ended_at if stream.ended_at is not None else datetime.now(UTC)
    duration_seconds = max((ended_at - stream.started_at).total_seconds(), 0.0)
    expected_samples = max(int(duration_seconds // VIEWER_SAMPLE_INTERVAL_SECONDS), 1)
    event_count = db.scalar(
        select(func.count()).select_from(Event).where(Event.stream_id == stream.id)
    )
    return {
        "duration_seconds": round(duration_seconds, 1),
        "chat": dict(chat_stats),
        "events": {"count": event_count},
        "viewers": {"samples": viewer_stats["samples"], "expected": expected_samples},
        "audio": dict(audio_stats),
    }
