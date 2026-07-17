"""The capture must end itself when Helix says the channel is offline.

Regression for the 2026-07-16 incident: a lost stream.offline webhook left a
stream CAPTURING for 9h. The sampler was already polling Helix every 60s, being
told the channel was offline, and threw that answer away. Worse, because
start_stream is idempotent per channel, the streamer's NEXT live got glued onto
the stale row (two lives in one stream row)."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from core.config import get_settings
from core.twitch import StreamInfo
from tests.factories import make_channel, make_stream
from workers.capture.collectors import OFFLINE_SAMPLES_TO_END, ViewerSampler

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

LIVE = StreamInfo(
    viewer_count=42,
    title="ao vivo",
    game_name="Elden Ring",
    started_at=datetime.now(UTC),
)


@pytest.fixture(autouse=True)
def _no_simulation(monkeypatch):
    """The repo .env turns simulation on, and in that mode the sampler reads
    Valkey instead of Helix (hanging on a socket that is not there in tests)."""
    monkeypatch.setenv("SIMULATION", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sampler(db, monkeypatch, responses):
    """A sampler whose Helix answers come from `responses` (None = offline) and
    whose DB work joins this test's transaction instead of opening its own."""
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=None)
    sampler = ViewerSampler(stream, channel)
    answers = iter(responses)
    monkeypatch.setattr(
        "workers.capture.collectors.get_stream_info", lambda _uid: next(answers)
    )
    monkeypatch.setattr(
        "workers.capture.collectors.session_factory",
        lambda: (lambda: nullcontext(db)),
    )
    return sampler, stream


def test_ends_stream_after_consecutive_offline_polls(db, monkeypatch) -> None:
    sampler, stream = _sampler(db, monkeypatch, [None] * OFFLINE_SAMPLES_TO_END)
    for _ in range(OFFLINE_SAMPLES_TO_END):
        sampler._sample_once()

    assert (
        stream.ended_at is not None
    ), "capture must end itself when Helix says offline"


def test_one_offline_poll_does_not_end_a_live_stream(db, monkeypatch) -> None:
    # a single empty Helix response is a blip, not the end of the live
    sampler, stream = _sampler(db, monkeypatch, [None])
    sampler._sample_once()

    assert stream.ended_at is None


def test_coming_back_online_resets_the_offline_streak(db, monkeypatch) -> None:
    # offline, offline, ONLINE, offline -> never OFFLINE_SAMPLES_TO_END in a row
    responses = [None] * (OFFLINE_SAMPLES_TO_END - 1) + [LIVE, None]
    sampler, stream = _sampler(db, monkeypatch, responses)
    for _ in range(len(responses)):
        sampler._sample_once()

    assert stream.ended_at is None
    assert sampler.stats["samples"] == 1  # only the online poll got recorded


def test_ended_at_is_when_the_channel_went_dark(db, monkeypatch) -> None:
    sampler, stream = _sampler(db, monkeypatch, [None] * OFFLINE_SAMPLES_TO_END)
    before = datetime.now(UTC)
    for _ in range(OFFLINE_SAMPLES_TO_END):
        sampler._sample_once()

    # the real end is the first offline poll, not the one that crossed the streak
    assert stream.ended_at is not None
    assert stream.ended_at - before < timedelta(seconds=5)


def test_does_not_overwrite_an_ended_at_the_webhook_already_set(
    db, monkeypatch
) -> None:
    sampler, stream = _sampler(db, monkeypatch, [None] * OFFLINE_SAMPLES_TO_END)
    webhook_end = datetime.now(UTC) - timedelta(minutes=5)
    stream.ended_at = webhook_end
    db.flush()

    for _ in range(OFFLINE_SAMPLES_TO_END):
        sampler._sample_once()

    assert stream.ended_at == webhook_end
