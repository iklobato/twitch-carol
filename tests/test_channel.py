"""Channel-level analytics across streams: loyalty, best weekday, growth,
recurring topics, and isolation."""

from datetime import UTC, datetime

import pytest

from core.models import InsightType
from tests.conftest import login_as
from tests.factories import (
    add_bits_leader,
    add_chat,
    add_event,
    add_follower,
    add_goal,
    add_insight,
    add_past_broadcast,
    add_segment,
    add_subscription,
    add_viewer_samples,
    add_vip,
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
    # the regular is a known follower (seeded like the connect backfill would)
    add_follower(db, channel, "regular")
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


def test_channel_finance_aggregates_across_streams(api_client, db) -> None:
    channel = make_channel(db)
    # a recurring spender across two streams, plus a topic that earns
    for offset_days, bits in ((14, 500), (7, 300)):
        stream = make_stream(
            db, channel, started_minutes_ago=offset_days * 24 * 60, duration_minutes=30
        )
        cheer = add_event(db, stream, "channel.cheer", offset_seconds=310, amount=bits)
        cheer.payload = {"user_login": "baleia", "bits": bits}
        segment = add_segment(db, stream, 300, "falando de deploy", duration_seconds=60)
        add_insight(
            db,
            stream,
            InsightType.TOPIC,
            "Deploy\nx",
            {"segment_ids": [segment.id], "message_ids": [], "rank": 1},
        )
    db.flush()

    login_as(api_client, channel)
    finance = api_client.get("/api/channel").json()["finance"]

    assert finance["total_bits"] == 800
    assert finance["total_estimated_usd"] == 8.0  # 800 bits * 0.01
    assert finance["top_contributors"][0]["login"] == "baleia"
    assert finance["top_contributors"][0]["streams"] == 2
    assert finance["top_monetizing_topics"][0]["name"] == "Deploy"
    assert finance["top_monetizing_topics"][0]["streams"] == 2


def test_channel_growth_carries_revenue(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, started_minutes_ago=100, title="Live paga")
    add_viewer_samples(db, stream, [10])
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=1000)
    cheer.payload = {"user_login": "fan"}
    db.flush()
    login_as(api_client, channel)
    growth = api_client.get("/api/channel").json()["growth"]
    assert growth[0]["estimated_usd"] == 10.0


def test_channel_followers_come_from_backfill_table(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, 3, author="regular")
    add_follower(db, channel, "regular")
    add_follower(db, channel, "silent_fan")  # follows but never chatted
    db.flush()

    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()

    assert overview["total_followers_gained"] == 2
    regular = next(
        c for c in overview["loyal_chatters"] if c["author_login"] == "regular"
    )
    assert regular["followed"] is True


def test_channel_followers_union_backfill_and_live_events(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_follower(db, channel, "backfilled_fan")
    # a live follow captured before the backfill table existed, events-only
    event = add_event(db, stream, "channel.follow")
    event.payload = {"user_login": "legacy_fan"}
    db.flush()

    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()

    assert overview["total_followers_gained"] == 2  # both sources, deduped by login


def test_channel_past_broadcasts_listed_newest_first(api_client, db) -> None:
    channel = make_channel(db)
    add_past_broadcast(db, channel, title="Live velha", published_minutes_ago=5000)
    add_past_broadcast(
        db, channel, title="Live recente", published_minutes_ago=100, view_count=42
    )
    db.flush()

    login_as(api_client, channel)
    broadcasts = api_client.get("/api/channel").json()["past_broadcasts"]

    assert [b["title"] for b in broadcasts] == ["Live recente", "Live velha"]
    assert broadcasts[0]["view_count"] == 42


def test_channel_content_revenue_by_category(api_client, db) -> None:
    channel = make_channel(db)
    # "Software" earns more per hour than "Just Chatting"
    coding = make_stream(db, channel, duration_minutes=60, title="Deploy")
    coding.category = "Software and Game Development"
    add_viewer_samples(db, coding, [40, 60])
    cheer = add_event(db, coding, "channel.cheer", offset_seconds=60, amount=2000)
    cheer.payload = {"user_login": "dev_fan"}
    chatting = make_stream(db, channel, duration_minutes=120, title="Papo")
    chatting.category = "Just Chatting"
    add_viewer_samples(db, chatting, [10])
    gift = add_event(db, chatting, "channel.cheer", offset_seconds=60, amount=500)
    gift.payload = {"user_login": "viewer"}
    db.flush()

    login_as(api_client, channel)
    content = api_client.get("/api/channel").json()["content_revenue"]

    by_cat = {c["category"]: c for c in content}
    assert by_cat["Software and Game Development"]["estimated_usd"] == 20.0  # 2000*.01
    assert by_cat["Software and Game Development"]["usd_per_hour"] == 20.0  # over 1h
    assert by_cat["Just Chatting"]["usd_per_hour"] == 2.5  # $5 over 2h
    # ranked by total revenue, Software first
    assert content[0]["category"] == "Software and Game Development"


def test_channel_content_revenue_skips_uncategorized(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=60)  # category stays None
    cheer = add_event(db, stream, "channel.cheer", offset_seconds=60, amount=1000)
    cheer.payload = {"user_login": "fan"}
    db.flush()

    login_as(api_client, channel)
    content = api_client.get("/api/channel").json()["content_revenue"]
    assert content == []  # revenue with no category is not attributed


def test_channel_engagement_hype_points_ads(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=60)
    add_viewer_samples(db, stream, [100, 100, 100])  # minutes 0,1,2
    hype = add_event(
        db, stream, "channel.hype_train.end", offset_seconds=200, amount=8000
    )
    hype.payload = {"level": 4, "total": 8000}
    redeem = "channel.channel_points_custom_reward_redemption.add"
    r1 = add_event(db, stream, redeem, offset_seconds=100)
    r1.payload = {"reward": {"title": "Pedir música"}}
    r2 = add_event(db, stream, redeem, offset_seconds=110)
    r2.payload = {"reward": {"title": "Pedir música"}}
    r3 = add_event(db, stream, redeem, offset_seconds=120)
    r3.payload = {"reward": {"title": "Destacar mensagem"}}
    ad = add_event(db, stream, "channel.ad_break.begin", offset_seconds=60, amount=60)
    ad.payload = {"duration_seconds": 60}
    db.flush()

    login_as(api_client, channel)
    eng = api_client.get("/api/channel").json()["engagement"]

    assert eng["hype_train"]["count"] == 1
    assert eng["hype_train"]["best_level"] == 4
    assert eng["hype_train"]["total_contributed"] == 8000
    assert eng["top_rewards"][0] == {"title": "Pedir música", "redemptions": 2}
    assert eng["ads"]["breaks"] == 1
    assert eng["ads"]["total_seconds"] == 60


def test_channel_engagement_empty_when_no_events(api_client, db) -> None:
    channel = make_channel(db)
    make_stream(db, channel)
    login_as(api_client, channel)
    eng = api_client.get("/api/channel").json()["engagement"]
    assert eng["hype_train"]["count"] == 0
    assert eng["top_rewards"] == []
    assert eng["ads"]["breaks"] == 0


def test_channel_community_goals_vips_engagement(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_viewer_samples(db, stream, [100])  # peak 100
    add_chat(db, stream, 4, author="a")
    add_chat(db, stream, 2, author="b")  # 2 distinct chatters over peak 100 = 2%
    add_vip(db, channel, "vip_carol")
    add_goal(db, channel, current_amount=750, target_amount=1000)
    db.flush()

    login_as(api_client, channel)
    community = api_client.get("/api/channel").json()["community"]

    assert community["vips"] == ["vip_carol"]
    assert community["goals"][0]["pct"] == 75.0
    assert community["engaged_viewer_pct"] == 2.0


def test_channel_subscribers_tiers_churn_bits(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_subscription(db, channel, "sub_a", tier="1000")
    add_subscription(db, channel, "sub_b", tier="1000")
    add_subscription(
        db, channel, "sub_c", tier="2000", is_gift=True, gifter_login="baleia"
    )
    add_bits_leader(db, channel, "whale", rank=1, score=5000)
    add_bits_leader(db, channel, "fan", rank=2, score=1200)
    # one sub ended during a stream (churn)
    add_event(db, stream, "channel.subscription.end", offset_seconds=30)
    db.flush()

    login_as(api_client, channel)
    subs = api_client.get("/api/channel").json()["subscribers"]

    assert subs["total"] == 3
    tier_map = {t["tier"]: t["count"] for t in subs["tiers"]}
    assert tier_map == {"1000": 2, "2000": 1}
    assert subs["gifted_pct"] == round(1 / 3 * 100, 1)
    assert subs["subs_ended"] == 1
    assert subs["top_bits"][0] == {"login": "whale", "score": 5000}


def test_channel_overview_empty(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    overview = api_client.get("/api/channel").json()
    assert overview["total_streams"] == 0
    assert overview["loyal_chatters"] == []
    assert overview["growth"] == []
    assert overview["finance"]["total_estimated_usd"] == 0.0
    assert overview["finance"]["top_contributors"] == []
    assert overview["past_broadcasts"] == []
    assert overview["content_revenue"] == []
    assert overview["community"]["vips"] == []
    assert overview["community"]["goals"] == []
    assert overview["subscribers"]["total"] == 0
    assert overview["subscribers"]["top_bits"] == []


def test_channel_requires_session(api_client) -> None:
    assert api_client.get("/api/channel").status_code == 401
