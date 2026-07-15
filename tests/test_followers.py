"""The /api/followers page: KPIs, growth, profiles, composition, AI decisions."""

from datetime import UTC, datetime, timedelta

import pytest

from core.models import FollowerRecommendation
from tests.conftest import login_as
from tests.factories import add_chat, add_follower, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def _seed(db, channel):
    old = datetime.now(UTC) - timedelta(days=800)
    young = datetime.now(UTC) - timedelta(days=10)
    add_follower(
        db,
        channel,
        "ana",
        broadcaster_type="affiliate",
        account_created_at=old,
        enriched=True,
        followed_minutes_ago=2 * 24 * 60,
    )
    add_follower(
        db,
        channel,
        "bruno",
        broadcaster_type="partner",
        account_created_at=old,
        enriched=True,
        followed_minutes_ago=5 * 24 * 60,
    )
    add_follower(
        db,
        channel,
        "caio",
        account_created_at=young,
        enriched=True,
        followed_minutes_ago=40 * 24 * 60,
    )
    stream = make_stream(db, channel)
    add_chat(db, stream, 3, author="ana")  # only ana chatted
    db.flush()


def test_followers_overview_sections(api_client, db) -> None:
    channel = make_channel(db)
    other = make_channel(db)
    _seed(db, channel)
    add_follower(db, other, "alheio", enriched=True)  # must not leak

    login_as(api_client, channel)
    body = api_client.get("/api/followers").json()

    kpis = body["kpis"]
    assert kpis["total"] == 3
    assert kpis["streamers"] == 2  # ana affiliate + bruno partner
    assert kpis["affiliates"] == 1
    assert kpis["partners"] == 1
    assert kpis["enriched"] == 3

    # notable = the two streamers; recent newest first
    notable_logins = {p["login"] for p in body["notable"]}
    assert notable_logins == {"ana", "bruno"}
    assert body["recent"][0]["login"] == "ana"  # followed most recently
    assert "alheio" not in {p["login"] for p in body["recent"]}

    # composition: only ana chatted -> 1 chatty, 2 silent
    assert body["composition"]["chatty"] == 1
    assert body["composition"]["silent"] == 2
    assert body["growth"][-1]["cumulative"] == 3


def test_followers_recommendations_passthrough(api_client, db) -> None:
    channel = make_channel(db)
    _seed(db, channel)
    db.add(
        FollowerRecommendation(
            channel_id=channel.id,
            content="Reative os silenciosos.",
            evidence={"facts": ["[1] 2 de 3 nunca escreveram no chat."]},
            model_used="fake",
        )
    )
    db.flush()

    login_as(api_client, channel)
    recs = api_client.get("/api/followers").json()["recommendations"]
    assert recs[0]["content"] == "Reative os silenciosos."
    assert recs[0]["facts"] == ["[1] 2 de 3 nunca escreveram no chat."]


def test_followers_empty(api_client, db) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    body = api_client.get("/api/followers").json()
    assert body["kpis"]["total"] == 0
    assert body["recent"] == []
    assert body["recommendations"] == []


def test_followers_requires_session(api_client) -> None:
    assert api_client.get("/api/followers").status_code == 401


def test_followers_funnel_value_and_loyalty(api_client, db) -> None:
    from tests.factories import add_event, make_stream

    channel = make_channel(db)
    add_follower(db, channel, "whale", enriched=True)
    add_follower(db, channel, "regular", enriched=True)
    add_follower(db, channel, "lurker", enriched=True)
    stream = make_stream(db, channel)
    add_chat(db, stream, 5, author="whale")
    add_chat(db, stream, 2, author="regular", badges={"subscriber": "12"})
    add_event(db, stream, "channel.cheer", amount=2000, login="whale")  # $20
    db.flush()

    login_as(api_client, channel)
    body = api_client.get("/api/followers").json()

    # funnel is cumulative: 3 follow, 2 chatted, 1 subscribed (badge), 1 paid
    stages = {s["stage"]: s["count"] for s in body["funnel"]}
    assert stages["seguidor"] == 3
    assert stages["engajado"] == 2
    assert stages["pagante"] == 1

    # whale tops the value table
    assert body["top_value"][0]["login"] == "whale"
    assert body["top_value"][0]["estimated_usd"] == 20.0

    # regular has the deepest sub badge -> leads loyalty
    assert body["loyal_subscribers"][0]["login"] == "regular"
    assert body["loyal_subscribers"][0]["sub_months"] == 12

    # one cohort row (all followed ~now), sizing the base
    assert sum(row["size"] for row in body["cohorts"]) == 3


def test_followers_collab_ranks_shared_category_first(api_client, db) -> None:
    from tests.factories import make_stream

    channel = make_channel(db)
    # the channel streams Valorant
    make_stream(db, channel, category="Valorant")

    # a streamer follower in the same category, one in another, one not enriched
    same = add_follower(db, channel, "matchx", broadcaster_type="affiliate", enriched=True)
    same.stream_category = "Valorant"
    same.stream_language = "pt"
    same.streamer_enriched_at = same.followed_at

    other = add_follower(db, channel, "lolplayer", broadcaster_type="partner", enriched=True)
    other.stream_category = "League of Legends"
    other.streamer_enriched_at = other.followed_at

    # affiliate but not streamer-enriched yet -> excluded from collab
    add_follower(db, channel, "pending", broadcaster_type="affiliate", enriched=True)
    db.flush()

    login_as(api_client, channel)
    collab = api_client.get("/api/followers").json()["collab"]

    logins = [c["login"] for c in collab]
    assert "pending" not in logins  # not streamer-enriched
    assert logins[0] == "matchx"  # shared category ranks first
    assert collab[0]["shared_category"] is True
    other_row = next(c for c in collab if c["login"] == "lolplayer")
    assert other_row["shared_category"] is False
