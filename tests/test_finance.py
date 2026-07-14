"""Financial breakdown from money events: totals, contributors, by-topic,
and the USD estimation."""

import pytest

from core.finance import event_usd
from core.models import Event, InsightType
from tests.conftest import login_as
from tests.factories import (
    add_event,
    add_insight,
    add_segment,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def _cheer(db, stream, login, bits, offset):
    event = add_event(db, stream, "channel.cheer", offset_seconds=offset, amount=bits)
    event.payload = {"user_login": login, "bits": bits}
    return event


def _sub(db, stream, login, tier, offset):
    event = add_event(
        db, stream, "channel.subscribe", offset_seconds=offset, amount=tier
    )
    event.payload = {"user_login": login, "tier": str(tier)}
    return event


def test_event_usd_estimation() -> None:
    cheer = Event(type="channel.cheer", amount=500, payload={})
    assert event_usd(cheer) == 5.0  # 500 bits * 0.01
    sub1 = Event(type="channel.subscribe", amount=1000, payload={})
    assert event_usd(sub1) == 2.5
    sub3 = Event(type="channel.subscribe", amount=3000, payload={})
    assert event_usd(sub3) == 12.5
    gift = Event(type="channel.subscription.gift", amount=5, payload={"tier": "1000"})
    assert event_usd(gift) == 12.5  # 5 gifted * 2.5
    assert event_usd(Event(type="channel.follow", amount=None, payload={})) == 0.0


def test_finance_totals_and_contributors(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    _cheer(db, stream, "generoso", 1000, 30)  # $10
    _cheer(db, stream, "modesto", 100, 60)  # $1
    _sub(db, stream, "generoso", 2000, 90)  # $5
    db.flush()

    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/finance").json()

    assert body["total_bits"] == 1100
    assert body["total_subs"] == 1
    assert body["estimated_usd"] == 16.0
    assert body["money_events"] == 3
    top = body["top_contributors"]
    assert top[0]["login"] == "generoso"
    assert top[0]["estimated_usd"] == 15.0
    assert top[0]["bits"] == 1000
    assert top[0]["subs"] == 1
    assert top[1]["login"] == "modesto"


def test_finance_by_topic(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=20)
    segment = add_segment(db, stream, 300, "falando de deploy", duration_seconds=60)
    add_insight(
        db,
        stream,
        InsightType.TOPIC,
        "Deploy\nx",
        {"segment_ids": [segment.id], "message_ids": [], "rank": 1},
    )
    # a cheer inside the topic window (300-360s, padded +-60s)
    _cheer(db, stream, "fan", 500, 310)
    db.flush()

    login_as(api_client, channel)
    by_topic = api_client.get(f"/api/streams/{stream.id}/finance").json()["by_topic"]
    assert by_topic[0]["name"] == "Deploy"
    assert by_topic[0]["estimated_usd"] == 5.0
    assert by_topic[0]["events"] == 1


def test_finance_empty_without_money_events(api_client, db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_event(db, stream, "channel.follow")  # not a money event
    db.flush()
    login_as(api_client, channel)
    body = api_client.get(f"/api/streams/{stream.id}/finance").json()
    assert body["estimated_usd"] == 0.0
    assert body["top_contributors"] == []


def test_finance_ownership(api_client, db) -> None:
    mine = make_channel(db)
    other = make_channel(db)
    foreign = make_stream(db, other)
    login_as(api_client, mine)
    assert api_client.get(f"/api/streams/{foreign.id}/finance").status_code == 404
