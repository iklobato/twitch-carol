"""Derived follower signals: raid attribution, fake-follow, velocity, topics."""

from datetime import UTC, datetime, timedelta

import pytest

from core.follower_signals import (
    follow_velocity,
    raid_attribution,
    suspicious_followers,
    topic_to_follows,
)
from tests.factories import (
    add_event,
    add_follower,
    add_segment,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_raid_attribution_counts_follows_in_window(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    # a raid at t+0, then two follows within 15 min and one long after
    add_event(
        db,
        stream,
        "channel.raid",
        offset_seconds=0,
        amount=80,
        payload={"from_broadcaster_user_login": "bigstreamer"},
    )
    add_event(db, stream, "channel.follow", offset_seconds=60, login="a")
    add_event(db, stream, "channel.follow", offset_seconds=120, login="b")
    add_event(db, stream, "channel.follow", offset_seconds=3600, login="c")
    db.flush()

    raids = raid_attribution(db, channel.id)
    assert len(raids) == 1
    assert raids[0].raider_login == "bigstreamer"
    assert raids[0].viewers == 80
    assert raids[0].follows_after == 2  # the two within 15 min, not the +1h one


def test_suspicious_followers_scores_botlike_profiles(db) -> None:
    channel = make_channel(db)
    now = datetime.now(UTC)
    # bot-like: young account, followed right after creating, no avatar, no bio
    young = now - timedelta(days=3)
    bot = add_follower(
        db,
        channel,
        "botlike",
        enriched=True,
        account_created_at=young,
        followed_at=young + timedelta(hours=1),
    )
    bot.profile_image_url = "https://cdn/user-default-x.png"
    bot.description = ""
    # legit: old account, has avatar and bio
    old = now - timedelta(days=900)
    legit = add_follower(db, channel, "legit", enriched=True, account_created_at=old)
    legit.profile_image_url = "https://cdn/legit.png"
    legit.description = "streamer de variedades"
    db.flush()

    flagged = suspicious_followers(db, channel.id, now)
    logins = [f.login for f in flagged]
    assert "botlike" in logins
    assert "legit" not in logins
    bot_row = next(f for f in flagged if f.login == "botlike")
    assert bot_row.score >= 4
    assert "no_avatar" in bot_row.reasons


def test_follow_velocity_flags_spike(db) -> None:
    channel = make_channel(db)
    base = datetime(2026, 6, 1, 12, tzinfo=UTC)
    # 8 quiet days (1 follow each), then a 40-follow spike day
    for day in range(8):
        add_follower(db, channel, f"s{day}", followed_at=base + timedelta(days=day))
    for i in range(40):
        add_follower(
            db, channel, f"spike{i}", followed_at=base + timedelta(days=9, minutes=i)
        )
    db.flush()

    velocity = follow_velocity(db, channel.id)
    spikes = [v for v in velocity if v.is_spike]
    assert len(spikes) == 1
    assert spikes[0].follows == 40


def test_topic_to_follows_correlates_window(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    seg = add_segment(db, stream, offset_seconds=100, duration_seconds=30)
    # a follow inside the topic's segment window
    add_event(db, stream, "channel.follow", offset_seconds=110, login="newbie")
    from core.models import Insight, InsightType

    db.add(
        Insight(
            stream_id=stream.id,
            type=InsightType.TOPIC,
            content="Novo mapa do jogo\ndescrição",
            evidence={"segment_ids": [seg.id]},
            model_used="fake",
            tokens_in=1,
            tokens_out=1,
        )
    )
    db.flush()

    topics = topic_to_follows(db, channel.id)
    assert len(topics) == 1
    assert topics[0].topic == "Novo mapa do jogo"
    assert topics[0].follows == 1


def test_signals_empty_without_data(db) -> None:
    channel = make_channel(db)
    assert raid_attribution(db, channel.id) == []
    assert follow_velocity(db, channel.id) == []
    assert topic_to_follows(db, channel.id) == []


def test_each_suspicious_reason_is_named_for_the_right_check(db) -> None:
    """The reasons now come back as boolean columns from the same SQL that scores
    the follower, so a flag wired to the wrong name would be invisible unless every
    one of them is pinned. This follower trips exactly two of the four."""
    channel = make_channel(db)
    now = datetime.now(UTC)
    old = now - timedelta(days=900)
    follower = add_follower(
        db, channel, "meio_suspeito", enriched=True, account_created_at=old
    )
    # old account, followed long after creating it: neither young nor fresh_follow
    follower.followed_at = now - timedelta(days=10)
    follower.profile_image_url = ""
    follower.description = "   "
    db.flush()

    # score 2 (no_avatar + no_bio) is under the threshold, so ask for the flags by
    # dropping a follower that also trips the other two into the same channel
    fresh = now - timedelta(days=2)
    other = add_follower(
        db,
        channel,
        "bem_suspeito",
        enriched=True,
        account_created_at=fresh,
        followed_at=fresh + timedelta(hours=2),
    )
    other.profile_image_url = "https://cdn/real.png"
    other.description = "bio de verdade"
    db.flush()

    flagged = {f.login: f for f in suspicious_followers(db, channel.id, now)}

    assert "meio_suspeito" not in flagged  # 2 points, under the threshold of 4
    assert set(flagged["bem_suspeito"].reasons) == {"young", "fresh_follow"}
    assert flagged["bem_suspeito"].score == 4
