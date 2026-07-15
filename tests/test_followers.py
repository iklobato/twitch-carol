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
