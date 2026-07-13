"""Channel-level analytics across streams: loyalty, best weekday, growth,
recurring topics, and isolation."""

from datetime import UTC, datetime

import pytest

from core.models import InsightType
from tests.conftest import login_as
from tests.factories import (
    add_chat,
    add_event,
    add_insight,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_channel_overview_loyalty_and_isolation(api_client, db) -> None:
    channel = make_channel(db)
    other = make_channel(db)
    # regular chatter present in all 3 streams; casual in only 1
    for days_ago in (21, 14, 7):
        stream = make_stream(db, channel, started_minutes_ago=days_ago * 24 * 60)
        add_chat(db, stream, 5, author="regular")
    casual_stream = make_stream(db, channel, started_minutes_ago=6 * 24 * 60)
    add_chat(db, casual_stream, 20, author="casual")
    # a follow event names the regular
    follow = add_event(db, make_stream(db, channel), "channel.follow")
    follow.payload = {"user_login": "regular"}
    db.flush()
    # another channel's chatter must not leak
    add_chat(db, make_stream(db, other), 50, author="alheio")

    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()

    logins = [c["author_login"] for c in overview["loyal_chatters"]]
    assert "alheio" not in logins
    regular = next(
        c for c in overview["loyal_chatters"] if c["author_login"] == "regular"
    )
    casual = next(
        c for c in overview["loyal_chatters"] if c["author_login"] == "casual"
    )
    # regular sorts above casual despite fewer total messages (3 streams > 1)
    assert regular["streams_attended"] == 3
    assert regular["total_messages"] == 15
    assert regular["followed"] is True
    assert casual["streams_attended"] == 1
    assert logins.index("regular") < logins.index("casual")


def test_channel_best_weekdays(api_client, db) -> None:
    channel = make_channel(db)
    # a Saturday stream with high viewers, a Wednesday with low
    saturday = datetime(2026, 7, 11, 20, tzinfo=UTC)  # 2026-07-11 is a Saturday
    wednesday = datetime(2026, 7, 8, 20, tzinfo=UTC)
    s1 = make_stream(db, channel, started_minutes_ago=0, duration_minutes=30)
    s1.started_at = saturday
    add_viewer_samples(db, s1, [100, 200])
    s2 = make_stream(db, channel, started_minutes_ago=0, duration_minutes=30)
    s2.started_at = wednesday
    add_viewer_samples(db, s2, [10, 20])
    db.flush()

    login_as(api_client, channel)
    weekdays = api_client.get("/api/channel").json()["best_weekdays"]
    # highest avg peak first
    assert weekdays[0]["label"] == "Sábado"
    assert weekdays[0]["avg_peak_viewers"] == 200.0


def test_channel_growth_and_recurring_topics(api_client, db) -> None:
    channel = make_channel(db)
    first = make_stream(db, channel, started_minutes_ago=2000, title="Live 1")
    add_viewer_samples(db, first, [10, 30])
    add_chat(db, first, 5)
    add_insight(
        db, first, InsightType.TOPIC, "Deploy\nx", {"segment_ids": [1], "rank": 1}
    )
    second = make_stream(db, channel, started_minutes_ago=100, title="Live 2")
    add_viewer_samples(db, second, [50, 90])
    add_insight(
        db, second, InsightType.TOPIC, "Deploy\ny", {"segment_ids": [2], "rank": 1}
    )
    add_insight(
        db, second, InsightType.TOPIC, "Caddy\nz", {"segment_ids": [3], "rank": 2}
    )
    db.flush()

    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()

    growth = overview["growth"]
    assert [g["title"] for g in growth] == ["Live 1", "Live 2"]  # chronological
    assert growth[0]["peak_viewers"] == 30
    assert growth[1]["peak_viewers"] == 90

    topics = {t["name"]: t["streams"] for t in overview["recurring_topics"]}
    assert topics["Deploy"] == 2  # appeared in both streams
    assert topics["Caddy"] == 1


def test_channel_overview_empty(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()
    assert overview["total_streams"] == 0
    assert overview["loyal_chatters"] == []
    assert overview["growth"] == []


def test_channel_requires_session(api_client) -> None:
    assert api_client.get("/api/channel").status_code == 401
