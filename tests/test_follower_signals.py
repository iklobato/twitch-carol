"""Derived follower signals: raid attribution, fake-follow, velocity, topics."""

from datetime import UTC, datetime, timedelta

import pytest

from core.follower_signals import (
    BASE_AGE_CONCENTRATED_SHARE,
    BASE_AGE_MIN_FOLLOWERS,
    base_age_concentration,
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


def _base_created_in(db, channel, months: list[int], per_month: int, year: int = 2023):
    """Followers whose accounts were created in the given months of `year`."""
    for month in months:
        for n in range(per_month):
            add_follower(
                db,
                channel,
                f"c{year}{month:02d}{n}",
                account_created_at=datetime(year, month, 1, tzinfo=UTC),
                followed_at=datetime(2026, 1, 1, tzinfo=UTC),
                enriched=True,
            )
    db.flush()


def test_a_base_made_in_one_window_is_flagged(db) -> None:
    """Measured in production 2026-08-12: 40,552 of matheustrem13's 41,605
    followers were accounts made in the first seven months of 2023, and the
    per-follower score flagged 2.4% of them, the lowest of all fourteen channels."""
    channel = make_channel(db)
    per_month = BASE_AGE_MIN_FOLLOWERS // 5 + 1
    _base_created_in(db, channel, [1, 2, 3, 4, 5], per_month)

    result = base_age_concentration(db, channel.id)

    assert result.followers_dated >= BASE_AGE_MIN_FOLLOWERS
    assert result.months_spanned == 5
    assert result.window_share == 1.0
    assert result.window_start == "2023-01"
    assert result.is_concentrated is True


def test_a_base_spread_over_years_is_not_flagged(db) -> None:
    channel = make_channel(db)
    per_year = BASE_AGE_MIN_FOLLOWERS // 5 + 1
    for year in (2019, 2021, 2023, 2025, 2026):
        _base_created_in(db, channel, [3], per_year, year=year)

    result = base_age_concentration(db, channel.id)

    assert result.months_spanned == 5
    # each year holds a fifth of the base, and no 6-month window spans two years
    assert result.window_share < BASE_AGE_CONCENTRATED_SHARE
    assert result.is_concentrated is False


def test_a_small_base_is_never_flagged(db) -> None:
    """A handful of followers clustering in one window is sample noise, not a
    bought base. iklobat's 42 followers reach 42.9% in six months on their own,
    and calling that fake would accuse a real streamer of buying an audience."""
    channel = make_channel(db)
    _base_created_in(db, channel, [1], 20)

    result = base_age_concentration(db, channel.id)

    assert result.window_share == 1.0
    assert result.followers_dated < BASE_AGE_MIN_FOLLOWERS
    assert result.is_concentrated is False


def test_a_channel_with_no_dated_followers_says_nothing(db) -> None:
    channel = make_channel(db)
    add_follower(db, channel, "sem_data")
    db.flush()

    result = base_age_concentration(db, channel.id)

    assert result.followers_dated == 0
    assert result.window_start is None
    assert result.is_concentrated is False
