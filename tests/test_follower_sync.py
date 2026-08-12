"""Follower sync: the walk, its resumability, and unfollow detection.

The tests that matter most here are the failure ones. Every bug this module was
written to fix showed up as data quietly missing in production, never as an error:
a channel stuck at exactly 20,000 followers, another with none at all, 20,000
rows with no profile on any of them.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from core.crypto import encrypt_secret
from core.follower_sync import (
    channels_due,
    enrich_followers,
    enrich_streamer_followers,
    sync_channel,
)
from core.models import Channel, Follower, Unfollow, UnfollowReason
from tests.factories import add_follower, make_channel

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def _with_fresh_token(db, channel: Channel) -> None:
    channel.access_token_encrypted = encrypt_secret("valid-token")
    channel.token_expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.flush()


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(_seconds: float) -> None:
    """Pacing is real in production and pointless in a test."""


def _follower_row(user_id: int, login: str, day: int) -> dict:
    return {
        "user_id": str(user_id),
        "user_login": login,
        "followed_at": f"2026-01-{day:02d}T00:00:00Z",
    }


def _app_token(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/oauth2/token"):
        return httpx.Response(200, json={"access_token": "app", "expires_in": 3600})
    return None


def _count_followers(db, channel: Channel) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Follower)
        .where(Follower.channel_id == channel.id)
    )


def test_total_comes_from_twitch_not_from_the_rows_we_hold(db) -> None:
    """The bug this whole change exists for. A channel with 41,605 followers was
    shown as 20,000 because the number was a count of our own rows."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        return httpx.Response(
            200,
            json={
                "total": 41605,
                "data": [_follower_row(11, "ana", 1)],
                "pagination": {},
            },
        )

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.total == 41605
    assert channel.follower_total == 41605
    # We hold one row and report 41,605. That difference is the honest state.
    assert _count_followers(db, channel) == 1


def test_a_failing_page_keeps_the_pages_already_committed(db) -> None:
    """This is the test that would have caught the production loss: the old code
    committed once at the end, so a failure on page two threw page one away."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "data": [_follower_row(11, "ana", 1)],
                    "pagination": {"cursor": "page-2"},
                },
            )
        return httpx.Response(500)

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.completed is False
    assert _count_followers(db, channel) == 1
    assert channel.follower_sync_cursor == "page-2"
    assert channel.follower_sync_error is not None
    # Not stamped as synced, so the worker comes back to it.
    assert channel.followers_synced_at is None


def test_an_interrupted_walk_resumes_from_the_stored_cursor(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    pass_started = datetime.now(UTC) - timedelta(minutes=10)
    ana = add_follower(db, channel, "ana", followed_minutes_ago=600)
    # ana came back on the page this walk already committed, so she carries the
    # pass mark. That mark is the whole point: it is what stops the resumed walk
    # from mistaking her for someone who left.
    ana.last_seen_at = pass_started
    channel.follower_sync_cursor = "page-2"
    channel.follower_sync_started_at = pass_started
    db.flush()
    seen_cursors = []

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            return httpx.Response(200, json={"data": []})
        seen_cursors.append(request.url.params.get("after"))
        return httpx.Response(
            200,
            json={
                "total": 2,
                "data": [_follower_row(22, "bruno", 2)],
                "pagination": {},
            },
        )

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert seen_cursors[0] == "page-2"  # picked up where it stopped
    assert result.completed is True
    assert _count_followers(db, channel) == 2
    assert channel.follower_sync_cursor is None


def test_a_completed_walk_records_who_left_and_keeps_their_name(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    staying = add_follower(db, channel, "ana", followed_minutes_ago=600, enriched=True)
    leaving = add_follower(
        db, channel, "bruno", followed_minutes_ago=600, enriched=True
    )
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            # Both accounts still exist, so neither is an account_gone case.
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": str(leaving.twitch_user_id),
                            "login": "bruno",
                            "display_name": "Bruno",
                            "created_at": "2020-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if request.url.params.get("user_id") is not None:
            # The per-person confirmation: Twitch says bruno is not a follower.
            return httpx.Response(200, json={"total": 1, "data": [], "pagination": {}})
        return httpx.Response(
            200,
            json={
                "total": 1,
                "data": [
                    _follower_row(staying.twitch_user_id, "ana", 1),
                ],
                "pagination": {},
            },
        )

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.unfollowed == 1
    gone = db.scalars(select(Unfollow).where(Unfollow.channel_id == channel.id)).all()
    assert len(gone) == 1
    assert gone[0].login == "bruno"
    assert gone[0].reason == UnfollowReason.UNFOLLOWED
    # The name and avatar are copied, because the followers row is deleted.
    assert gone[0].display_name == "Bruno"
    assert gone[0].profile_image_url is not None
    assert _count_followers(db, channel) == 1


def test_a_follower_twitch_still_confirms_is_not_recorded_as_gone(db) -> None:
    """Cursor pagination over a list people are joining and leaving can skip a
    row. Deleting a real follower over that is worse than counting one for
    another six hours, so every candidate is confirmed first."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    skipped = add_follower(db, channel, "ana", followed_minutes_ago=600, enriched=True)
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": str(skipped.twitch_user_id),
                            "login": "ana",
                            "display_name": "Ana",
                            "created_at": "2020-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if request.url.params.get("user_id") is not None:
            # Asked directly, Twitch confirms the follow. It was a paging gap.
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "data": [_follower_row(skipped.twitch_user_id, "ana", 1)],
                    "pagination": {},
                },
            )
        return httpx.Response(200, json={"total": 1, "data": [], "pagination": {}})

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.unfollowed == 0
    assert _count_followers(db, channel) == 1
    assert db.scalars(select(Unfollow)).all() == []


def test_a_removed_account_is_not_called_an_unfollow(db) -> None:
    """A banned or deleted account also drops out of the list. Telling a streamer
    that person unfollowed them would be untrue, so it gets its own reason and is
    kept off the unfollow list the screen shows."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    add_follower(db, channel, "banned", followed_minutes_ago=600, enriched=True)
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            return httpx.Response(200, json={"data": []})  # Twitch knows nobody
        return httpx.Response(200, json={"total": 0, "data": [], "pagination": {}})

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.accounts_gone == 1
    assert result.unfollowed == 0
    gone = db.scalars(select(Unfollow)).all()
    assert [row.reason for row in gone] == [UnfollowReason.ACCOUNT_GONE]


def test_a_follow_that_arrived_mid_walk_is_never_treated_as_an_unfollow(db) -> None:
    """The live channel.follow event writes rows while a walk is in progress. The
    walk never had a chance to see them, so they must not look like departures."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    # A walk in progress since ten minutes ago, and a follow that landed after it
    # started. The walk cannot have seen this person, so a missing pass mark here
    # means nothing.
    channel.follower_sync_cursor = "page-2"
    channel.follower_sync_started_at = datetime.now(UTC) - timedelta(minutes=10)
    add_follower(db, channel, "arrived_now", followed_minutes_ago=0)
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"total": 1, "data": [], "pagination": {}})

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.unfollowed == 0
    assert result.accounts_gone == 0
    assert _count_followers(db, channel) == 1


def test_channels_due_puts_never_synced_channels_first(db) -> None:
    now = datetime.now(UTC)
    fresh = make_channel(db)
    fresh.followers_synced_at = now - timedelta(minutes=5)
    stale = make_channel(db)
    stale.followers_synced_at = now - timedelta(days=1)
    never = make_channel(db)
    db.flush()

    due = channels_due(db, now)

    assert [c.id for c in due][:2] == [never.id, stale.id]
    assert fresh.id not in [c.id for c in due]


def test_enrich_followers_fills_profiles_and_stamps_missing(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    ana = add_follower(db, channel, "ana")
    bruno = add_follower(db, channel, "bruno")
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        # Twitch returns only ana; bruno is absent (banned or deleted)
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

    enriched = enrich_followers(db, channel, _mock_client(handler), _no_sleep)
    assert enriched == 1

    ana_row = db.scalar(
        select(Follower).where(Follower.twitch_user_id == ana.twitch_user_id)
    )
    assert ana_row.display_name == "Ana"
    assert ana_row.broadcaster_type == "affiliate"
    assert ana_row.account_created_at == datetime(2020, 1, 1, tzinfo=UTC)
    assert ana_row.enriched_at is not None

    # bruno was not returned, but must be stamped so it is not retried forever,
    # and so the batch loop can terminate at all.
    bruno_row = db.scalar(
        select(Follower).where(Follower.twitch_user_id == bruno.twitch_user_id)
    )
    assert bruno_row.enriched_at is not None
    assert bruno_row.broadcaster_type is None

    assert enrich_followers(db, channel, _mock_client(handler), _no_sleep) == 0


def test_enrich_streamer_followers_fills_category(db) -> None:
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    streamer = add_follower(db, channel, "streamerx", broadcaster_type="affiliate")
    add_follower(db, channel, "common")  # broadcaster_type None -> skipped
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "broadcaster_id": str(streamer.twitch_user_id),
                        "broadcaster_language": "pt",
                        "game_name": "Valorant",
                        "title": "ranqueada",
                    }
                ]
            },
        )

    enriched = enrich_streamer_followers(db, channel, _mock_client(handler), _no_sleep)
    assert enriched == 1

    row = db.scalar(
        select(Follower).where(Follower.twitch_user_id == streamer.twitch_user_id)
    )
    assert row.stream_category == "Valorant"
    assert row.stream_language == "pt"
    assert row.streamer_enriched_at is not None
    assert enrich_streamer_followers(db, channel, _mock_client(handler), _no_sleep) == 0


def test_a_candidate_list_bigger_than_the_channel_is_refused_not_deleted(db) -> None:
    """Measured on dev on 2026-08-11: a database carrying another channel's
    followers produced 20,570 candidates for a channel Twitch reports 42 followers
    for, and the pass deleted 200 of them. Confirming each one does not help,
    because the confirmation asks the same API that produced the number."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    for n in range(30):
        add_follower(db, channel, f"nao_segue_{n}", followed_minutes_ago=600)
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            raise AssertionError("must refuse before spending a single call")
        return httpx.Response(200, json={"total": 42, "data": [], "pagination": {}})

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.unfollowed == 0
    assert result.accounts_gone == 0
    assert result.unfollows_deferred == 30
    assert _count_followers(db, channel) == 30
    assert db.scalars(select(Unfollow)).all() == []
    # The refusal has to be visible, not just absent from the counters.
    assert channel.follower_sync_error is not None
    assert "refusing to delete" in channel.follower_sync_error


def test_a_believable_number_of_departures_still_goes_through(db) -> None:
    """The guard must not block the thing the feature exists for. A base of 42 with
    two people gone is under the floor and has to be processed normally."""
    channel = make_channel(db)
    _with_fresh_token(db, channel)
    left = add_follower(db, channel, "saiu", followed_minutes_ago=600, enriched=True)
    db.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        app = _app_token(request)
        if app is not None:
            return app
        if "/users" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": str(left.twitch_user_id),
                            "login": "saiu",
                            "display_name": "Saiu",
                            "created_at": "2020-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if request.url.params.get("user_id") is not None:
            return httpx.Response(200, json={"total": 42, "data": [], "pagination": {}})
        return httpx.Response(200, json={"total": 42, "data": [], "pagination": {}})

    result = sync_channel(db, channel, _mock_client(handler), _no_sleep)

    assert result.unfollowed == 1
    assert channel.follower_sync_error is None
