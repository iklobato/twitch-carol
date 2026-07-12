"""Stream lifecycle: online creates, offline marks ended; the capture worker
finalizes (audit + queue) after its collectors stop."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Channel, Stream, StreamStatus

logger = logging.getLogger(__name__)


def get_active_stream(db: Session, channel_id: int) -> Stream | None:
    return db.scalar(
        select(Stream)
        .where(Stream.channel_id == channel_id)
        .where(Stream.status == StreamStatus.CAPTURING)
        .where(Stream.ended_at.is_(None))
        .order_by(Stream.started_at.desc())
    )


def start_stream(db: Session, channel: Channel, started_at: datetime) -> Stream:
    """Idempotent: a duplicate stream.online returns the already-active stream."""
    active = get_active_stream(db, channel.id)
    if active is not None:
        return active
    stream = Stream(
        channel_id=channel.id, started_at=started_at, status=StreamStatus.CAPTURING
    )
    db.add(stream)
    db.flush()
    logger.info(
        "stream started", extra={"stream_id": stream.id, "channel_id": channel.id}
    )
    return stream


def mark_stream_offline(db: Session, stream: Stream, ended_at: datetime) -> None:
    """Only sets ended_at; status stays CAPTURING until the capture worker
    finalizes collectors, writes the audit and enqueues transcription."""
    if stream.ended_at is not None:
        return
    stream.ended_at = ended_at
    db.flush()
    logger.info(
        "stream marked offline",
        extra={"stream_id": stream.id, "channel_id": stream.channel_id},
    )
