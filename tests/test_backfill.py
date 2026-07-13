"""Connect-time backfill: seed followers and past broadcasts from Helix."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from core.backfill import backfill_followers, backfill_videos
from core.crypto import encrypt_secret
from core.models import Channel, Follower, PastBroadcast
from tests.factories import make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def _with_fresh_token(db, channel: Channel) -> None:
    channel.access_token_encrypted = encrypt_secret("valid-token")
    channel.token_expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.flush()


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _followers_handler(records: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": records, "pagination": {}})

    return handler


def test_backfill_followers_inserts_and_is_idempotent(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    records = [
        {"user_id": "11", "user_login": "ana", "followed_at": "2026-01-01T00:00:00Z"},
        {"user_id": "22", "user_login": "bruno", "followed_at": "2026-01-02T00:00:00Z"},
    ]

    added = backfill_followers(
        db, channel, client=_mock_client(_followers_handler(records))
    )
    db.flush()
    assert added == 2

    logins = set(
        db.scalars(select(Follower.login).where(Follower.channel_id == channel.id))
    )
    assert logins == {"ana", "bruno"}

    # re-connecting must not duplicate
    again = backfill_followers(
        db, channel, client=_mock_client(_followers_handler(records))
    )
    db.flush()
    assert again == 0
    total = db.scalar(
        select(func.count())
        .select_from(Follower)
        .where(Follower.channel_id == channel.id)
    )
    assert total == 2


def test_backfill_videos_inserts_then_refreshes_views(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)

    def handler_with(view_count: str):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "v1",
                            "title": "Primeira live",
                            "created_at": "2026-02-01T20:00:00Z",
                            "duration": "27m",
                            "view_count": view_count,
                            "url": "https://twitch.tv/videos/v1",
                        }
                    ]
                },
            )

        return handler

    added = backfill_videos(db, channel, client=_mock_client(handler_with("10")))
    db.flush()
    assert added == 1
    row = db.scalar(select(PastBroadcast).where(PastBroadcast.channel_id == channel.id))
    assert row.duration_seconds == 27 * 60
    assert row.view_count == 10

    # a later connect refreshes the view count without adding a row
    again = backfill_videos(db, channel, client=_mock_client(handler_with("99")))
    db.flush()
    assert again == 0
    refreshed = db.scalar(
        select(PastBroadcast.view_count).where(PastBroadcast.channel_id == channel.id)
    )
    assert refreshed == 99
