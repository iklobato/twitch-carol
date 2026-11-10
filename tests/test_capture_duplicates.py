"""Two capture workers on the same live must not double any data.

A standby capture worker runs next to the official one so a deploy or crash of
either loses nothing. Both read the same IRC channel and the same Helix numbers,
so every write has to be idempotent. Regression for the 2026-07-16 incident,
where two workers captured streams 39-44 at once and left duplicate chat rows
and duplicate viewer samples in production."""

import asyncio
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Channel, ChatMessage, Job, Stream, StreamStatus, ViewerSample
from core.queues import JOB_TRANSCRIBE
from core.twitch import StreamInfo
from tests.factories import make_channel, make_stream
from tests.fake_twitch import irc_line
from workers.capture.clip_detector import ClipDetector, NeverClipDetector
from workers.capture.collectors import ChatCollector, ViewerSampler
from workers.capture.session import CaptureSession

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

VIEWERS_NOW = 42


@pytest.fixture(autouse=True)
def _no_simulation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The repo .env turns simulation on; these tests read Helix through a fake."""
    monkeypatch.setenv("SIMULATION", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def capturing(db: Session, monkeypatch: pytest.MonkeyPatch) -> tuple[Stream, Channel]:
    """A live stream whose collectors write inside this test's transaction."""
    live = StreamInfo(
        viewer_count=VIEWERS_NOW,
        title="ao vivo",
        game_name="Elden Ring",
        started_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "workers.capture.collectors.session_factory", lambda: lambda: nullcontext(db)
    )
    monkeypatch.setattr("workers.capture.collectors.get_stream_info", lambda _uid: live)
    channel = make_channel(db)
    stream = make_stream(db, channel, status=StreamStatus.CAPTURING, duration_minutes=None)
    return stream, channel


def test_same_chat_message_from_two_workers_is_stored_once(
    db: Session, capturing: tuple[Stream, Channel]
) -> None:
    stream, channel = capturing
    line = irc_line(channel.login, "viewer_1", "GG", datetime.now(UTC))
    primary = ChatCollector(stream, channel, ClipDetector())
    standby = ChatCollector(stream, channel, NeverClipDetector())

    for collector in (primary, standby):
        collector.ingest(line)
        collector.flush()

    stored = db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.stream_id == stream.id)
    )
    assert stored == 1, f"one IRC message read by two workers became {stored} rows"


def test_viewer_samples_from_two_workers_in_one_minute_are_stored_once(
    db: Session, capturing: tuple[Stream, Channel]
) -> None:
    stream, channel = capturing
    primary, standby = ViewerSampler(stream, channel), ViewerSampler(stream, channel)

    for sampler in (primary, standby):
        sampler.sample_once()

    stored = db.scalar(
        select(func.count()).select_from(ViewerSample).where(ViewerSample.stream_id == stream.id)
    )
    assert stored == 1, f"two workers sampling the same minute left {stored} samples"


def test_live_finalized_by_two_workers_queues_one_transcription(
    db: Session, capturing: tuple[Stream, Channel]
) -> None:
    stream, channel = capturing
    stream.ended_at = datetime.now(UTC)
    db.flush()
    workers = (CaptureSession.for_live(stream, channel), CaptureSession.for_live(stream, channel))

    for worker in workers:
        asyncio.run(worker.stop_and_finalize(lambda: nullcontext(db)))

    jobs = db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.stream_id == stream.id, Job.type == JOB_TRANSCRIBE)
    )
    assert jobs == 1, f"two workers finalizing one live queued {jobs} transcriptions"
