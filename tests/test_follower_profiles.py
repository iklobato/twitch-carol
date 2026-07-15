"""Per-follower feature rows crossing followers with chat, money, and subs."""

import pytest

from core.follower_profiles import build_follower_profiles
from tests.factories import (
    add_chat,
    add_event,
    add_follower,
    add_subscription,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_profiles_cross_chat_money_and_subs(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_follower(db, channel, "payer")
    add_follower(db, channel, "chatter")
    add_follower(db, channel, "lurker")

    add_chat(db, stream, 4, author="payer")
    add_chat(db, stream, 2, author="chatter")
    add_event(db, stream, "channel.cheer", amount=1000, login="payer")  # bits -> USD
    add_subscription(db, channel, "payer", tier="2000")
    db.flush()

    profiles = {p.login: p for p in build_follower_profiles(db, channel.id)}

    # payer reached the deepest stage and sorts first (most value)
    assert profiles["payer"].stage == "pagante"
    assert profiles["payer"].estimated_usd > 0
    assert profiles["payer"].messages == 4
    assert profiles["payer"].is_subscriber is True

    assert profiles["chatter"].stage == "engajado"
    assert profiles["chatter"].estimated_usd == 0.0
    assert profiles["lurker"].stage == "seguidor"
    assert profiles["lurker"].messages == 0


def test_badge_months_are_read_from_chat(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_follower(db, channel, "veterano")
    # a subscriber badge version is the tenure in months
    add_chat(db, stream, 1, author="veterano", badges={"subscriber": "18"})
    db.flush()

    profile = next(
        p for p in build_follower_profiles(db, channel.id) if p.login == "veterano"
    )
    assert profile.sub_months == 18
    assert profile.is_subscriber is True
    assert profile.stage == "inscrito"


def test_profiles_ordered_by_value_then_messages(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_follower(db, channel, "rico")
    add_follower(db, channel, "tagarela")
    add_event(db, stream, "channel.cheer", amount=500, login="rico")
    add_chat(db, stream, 10, author="tagarela")
    db.flush()

    profiles = build_follower_profiles(db, channel.id)
    assert profiles[0].login == "rico"  # value beats message volume


def test_no_followers_returns_empty(db) -> None:
    channel = make_channel(db)
    assert build_follower_profiles(db, channel.id) == []
