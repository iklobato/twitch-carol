"""Connect-time backfill: seed followers and past broadcasts from Helix."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from core.backfill import (
    backfill_bits_leaders,
    backfill_followers,
    backfill_goals,
    backfill_subscriptions,
    backfill_videos,
    backfill_vips,
    enrich_followers,
)
from core.crypto import encrypt_secret
from core.models import (
    BitsLeader,
    Channel,
    Follower,
    Goal,
    PastBroadcast,
    Subscription,
    Vip,
)
from tests.factories import add_follower, make_channel

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


def test_backfill_vips_inserts_and_dedups(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    records = [
        {"user_id": "1", "user_login": "vip_ana"},
        {"user_id": "2", "user_login": "vip_bruno"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": records, "pagination": {}})

    added = backfill_vips(db, channel, client=_mock_client(handler))
    db.flush()
    assert added == 2
    logins = set(db.scalars(select(Vip.login).where(Vip.channel_id == channel.id)))
    assert logins == {"vip_ana", "vip_bruno"}
    assert backfill_vips(db, channel, client=_mock_client(handler)) == 0


def test_backfill_goals_replaces_snapshot(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)

    def handler_with(current: int):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "g1",
                            "type": "follower",
                            "description": "1k seguidores",
                            "current_amount": current,
                            "target_amount": 1000,
                            "created_at": "2026-07-01T12:00:00Z",
                        }
                    ]
                },
            )

        return handler

    backfill_goals(db, channel, client=_mock_client(handler_with(500)))
    db.flush()
    goal = db.scalar(select(Goal).where(Goal.channel_id == channel.id))
    assert goal.current_amount == 500
    assert goal.created_at == datetime(2026, 7, 1, 12, tzinfo=UTC)

    # a later connect refreshes progress in place
    backfill_goals(db, channel, client=_mock_client(handler_with(750)))
    db.flush()
    refreshed = db.scalar(
        select(Goal.current_amount).where(Goal.channel_id == channel.id)
    )
    assert refreshed == 750


def test_backfill_subscriptions_replaces_snapshot(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "user_id": "1",
                        "user_login": "sub_a",
                        "tier": "1000",
                        "is_gift": False,
                    },
                    {
                        "user_id": "2",
                        "user_login": "sub_b",
                        "tier": "2000",
                        "is_gift": True,
                        "gifter_login": "baleia",
                    },
                ],
                "pagination": {},
            },
        )

    added = backfill_subscriptions(db, channel, client=_mock_client(handler))
    db.flush()
    assert added == 2
    tiers = {
        s.login: s.tier
        for s in db.scalars(
            select(Subscription).where(Subscription.channel_id == channel.id)
        )
    }
    assert tiers == {"sub_a": "1000", "sub_b": "2000"}
    # a re-connect replaces, not duplicates
    assert backfill_subscriptions(db, channel, client=_mock_client(handler)) == 2
    total = db.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.channel_id == channel.id)
    )
    assert total == 2


def test_backfill_bits_leaders_replaces_snapshot(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"user_login": "whale", "rank": 1, "score": 5000},
                    {"user_login": "fan", "rank": 2, "score": 1200},
                ]
            },
        )

    added = backfill_bits_leaders(db, channel, client=_mock_client(handler))
    db.flush()
    assert added == 2
    top = db.scalar(
        select(BitsLeader.login)
        .where(BitsLeader.channel_id == channel.id)
        .order_by(BitsLeader.rank)
    )
    assert top == "whale"


def test_enrich_followers_fills_profiles_and_stamps_missing(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    ana = add_follower(db, channel, "ana")
    bruno = add_follower(db, channel, "bruno")
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "app", "expires_in": 3600})
        # Twitch returns only ana; bruno is absent (e.g. banned/deleted)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": str(ana.twitch_user_id),
                        "login": "ana",
                        "display_name": "Ana",
                        "profile_image_url": "https://cdn/ana.png",
                        "description": "streamer de variedades",
                        "broadcaster_type": "affiliate",
                        "created_at": "2020-01-01T00:00:00Z",
                    }
                ]
            },
        )

    enriched = enrich_followers(db, channel, client=_mock_client(handler))
    db.flush()
    assert enriched == 1

    ana_row = db.scalar(
        select(Follower).where(Follower.twitch_user_id == ana.twitch_user_id)
    )
    assert ana_row.display_name == "Ana"
    assert ana_row.broadcaster_type == "affiliate"
    assert ana_row.account_created_at == datetime(2020, 1, 1, tzinfo=UTC)
    assert ana_row.enriched_at is not None

    # bruno was not returned, but must be stamped so it is not retried forever
    bruno_row = db.scalar(
        select(Follower).where(Follower.twitch_user_id == bruno.twitch_user_id)
    )
    assert bruno_row.enriched_at is not None
    assert bruno_row.broadcaster_type is None

    # a second run has nothing pending
    assert enrich_followers(db, channel, client=_mock_client(handler)) == 0
