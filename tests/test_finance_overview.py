"""Account-wide /api/finance overview: the analysis-period window resolver,
period-scoped money folding, delta vs the previous window, and consolidation
of the non-money monetization signals (hype trains, ads, points, goals)."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.api.finance import Period, resolve_period_window
from tests.conftest import login_as
from tests.factories import add_event, add_goal, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")

DAY_MINUTES = 24 * 60


def _cheer(db, stream, login, bits, offset=30):
    return add_event(
        db, stream, "channel.cheer", offset_seconds=offset, amount=bits, login=login
    )


def test_resolve_period_window_uses_days_and_a_comparison_window() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    start, previous_start = resolve_period_window(Period.P30, now)
    assert start == now - timedelta(days=30)
    assert previous_start == now - timedelta(days=60)


def test_resolve_period_window_all_has_no_comparison() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    assert resolve_period_window(Period.ALL, now) == (None, None)


def test_finance_period_scopes_money_to_the_window(api_client, db) -> None:
    channel = make_channel(db)
    recent = make_stream(db, channel, started_minutes_ago=10 * DAY_MINUTES)
    old = make_stream(db, channel, started_minutes_ago=45 * DAY_MINUTES)
    _cheer(db, recent, "ana", 1000)  # $10, inside 30d
    _cheer(db, old, "bia", 2000)  # $20, outside 30d
    db.flush()
    login_as(api_client, channel)

    scoped = api_client.get("/api/finance?period=30d").json()
    assert scoped["estimated_usd"] == 10.0
    assert scoped["total_bits"] == 1000
    assert scoped["money_events"] == 1
    assert [row["estimated_usd"] for row in scoped["by_stream"]] == [10.0]

    everything = api_client.get("/api/finance?period=all").json()
    assert everything["estimated_usd"] == 30.0
    assert everything["delta_pct"] is None  # no comparison window for "all"


def test_finance_delta_compares_against_previous_window(api_client, db) -> None:
    channel = make_channel(db)
    current = make_stream(db, channel, started_minutes_ago=10 * DAY_MINUTES)
    prior = make_stream(db, channel, started_minutes_ago=45 * DAY_MINUTES)
    _cheer(db, current, "ana", 1500)  # $15 this window
    _cheer(db, prior, "bia", 1000)  # $10 previous window (30-60d ago)
    db.flush()
    login_as(api_client, channel)

    body = api_client.get("/api/finance?period=30d").json()
    assert body["estimated_usd"] == 15.0
    assert body["delta_pct"] == 50.0  # (15 - 10) / 10 * 100


def test_finance_overview_empty_without_money(api_client, db) -> None:
    channel = make_channel(db)
    make_stream(db, channel, started_minutes_ago=60)
    db.flush()
    login_as(api_client, channel)

    body = api_client.get("/api/finance").json()
    assert body["estimated_usd"] == 0.0
    assert body["delta_pct"] is None
    assert body["by_stream"] == []
    assert body["top_contributors"] == []


def test_finance_overview_consolidates_engagement_and_goals(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, started_minutes_ago=5 * DAY_MINUTES)
    add_event(db, stream, "channel.hype_train.end", amount=5000, payload={"level": 3})
    add_event(db, stream, "channel.ad_break.begin", amount=90)
    add_event(
        db,
        stream,
        "channel.channel_points_custom_reward_redemption.add",
        payload={"reward": {"title": "Escolher música"}},
    )
    add_goal(db, channel, goal_type="sub", current_amount=40, target_amount=100)
    db.flush()
    login_as(api_client, channel)

    body = api_client.get("/api/finance?period=30d").json()
    hype = body["engagement"]["hype_train"]
    assert hype["count"] == 1
    assert hype["best_level"] == 3
    assert body["engagement"]["ads"]["breaks"] == 1
    assert body["engagement"]["top_rewards"][0]["title"] == "Escolher música"
    assert body["goals"][0]["goal_type"] == "sub"
    assert body["goals"][0]["pct"] == 40.0
