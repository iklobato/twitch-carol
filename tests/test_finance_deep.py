"""Deep finance metrics: revenue/hour, churn, and moment-level attribution."""

from tests.conftest import login_as
from tests.factories import add_event, add_subscription, make_channel, make_stream

DAY = 24 * 60


def test_revenue_per_hour(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    stream = make_stream(db, channel, started_minutes_ago=5 * DAY, duration_minutes=30)
    add_event(db, stream, "channel.cheer", offset_seconds=30, amount=500, login="bob")

    body = api_client.get("/api/finance").json()

    assert body["streamed_hours"] == 0.5
    assert body["total_revenue_usd"] == 5.0  # 500 bits * $0.01
    assert body["revenue_per_hour_usd"] == 10.0  # $5 / 0.5h


def test_churn_metrics(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    for i in range(10):  # 10 currently-active subs
        add_subscription(db, channel, login=f"sub{i}")
    stream = make_stream(db, channel, started_minutes_ago=5 * DAY, duration_minutes=60)
    for i in range(3):  # 3 new subs
        add_event(db, stream, "channel.subscribe", offset_seconds=10 + i, amount=1000)
    add_event(db, stream, "channel.subscription.gift", offset_seconds=20, amount=2)
    for i in range(4):  # 4 churned
        add_event(db, stream, "channel.subscription.end", offset_seconds=30 + i)

    subs = api_client.get("/api/finance").json()["subscribers"]

    assert subs["subs_gained"] == 5  # 3 new + 2 gifted
    assert subs["subs_ended"] == 4
    assert subs["net_subs"] == 1
    # active_at_start = 10 - 5 + 4 = 9; churn = 4/9 * 100
    assert subs["churn_pct"] == 44.4


def test_top_moments_rank_and_annotate(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    stream = make_stream(db, channel, started_minutes_ago=5 * DAY, duration_minutes=60)
    add_event(db, stream, "channel.cheer", offset_seconds=100, amount=1000, login="bob")
    add_event(
        db, stream, "channel.subscribe", offset_seconds=200, amount=1000, login="ann"
    )

    moments = api_client.get(f"/api/streams/{stream.id}/finance").json()["top_moments"]

    assert len(moments) == 2
    assert moments[0]["estimated_usd"] == 10.0  # the cheer, ranked first
    assert moments[0]["kind"] == "bits"
    assert moments[0]["offset_seconds"] == 100
    assert moments[0]["contributor"] == "bob"
    assert moments[1]["kind"] == "sub"
    assert moments[1]["estimated_usd"] == 2.5
