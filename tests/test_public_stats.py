"""Public platform stats for the landing page: aggregate counts, no auth, cached."""

import pytest

import apps.api.public as public_mod
from core.models import StreamStatus
from tests.factories import (
    add_chat,
    add_segment,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    # the endpoint caches in module globals; reset so each test recomputes
    monkeypatch.setattr(public_mod, "_cached", None)
    monkeypatch.setattr(public_mod, "_cached_at", 0.0)


def test_stats_counts_are_public_and_correct(api_client, db) -> None:
    channel = make_channel(db)
    ready = make_stream(db, channel, status=StreamStatus.READY, duration_minutes=90)
    add_chat(db, ready, count=12)
    add_segment(db, ready, 10, "oi pessoal")
    add_segment(db, ready, 40, "bora jogar")
    add_viewer_samples(db, ready, [10, 20])
    # a still-capturing live: counts toward chat/hours but not "analyzed"
    live = make_stream(db, channel, status=StreamStatus.CAPTURING, duration_minutes=30)
    add_chat(db, live, count=3)
    db.flush()

    # no login_as: the endpoint must answer without a session
    resp = api_client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chat_messages"] == 15  # 12 + 3, both lives
    assert body["streams_analyzed"] == 1  # only the READY one
    assert body["hours_captured"] == 2  # 90 + 30 min = 120 min -> 2h
    assert body["segments_transcribed"] == 2


def test_stats_are_cached(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, status=StreamStatus.READY)
    add_chat(db, stream, count=5)
    db.flush()

    first = api_client.get("/api/stats").json()
    assert first["chat_messages"] == 5

    add_chat(db, stream, count=100)  # more data after the first call
    db.flush()
    second = api_client.get("/api/stats").json()
    assert second["chat_messages"] == 5  # served from cache, not recomputed
