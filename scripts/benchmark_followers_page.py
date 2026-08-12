"""Times each part of the followers page against a base the size of the biggest
real channel, so the slow part is measured instead of guessed.

Production's largest channel holds 41,605 followers, and the page measured 7.2s
on dev with 20,612. The repo's own notes warn that on /api/channel the SQL was
only ~450ms of a ~4s request and the rest was application work, so the same
assumption is not worth making twice.

    DATABASE_URL=postgresql+psycopg://app:app@localhost:5434/bench_followers \
    FERNET_KEY=... TWITCH_CLIENT_ID=x TWITCH_CLIENT_SECRET=y \
    alembic upgrade head          # chat_messages is partitioned; create_all cannot
    python -m scripts.benchmark_followers_page [followers] [chatters]
"""

import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.db import ensure_chat_partition, session_factory
from core.models import Channel, ChatMessage, Follower, Stream, StreamStatus

FOLLOWERS = 41_605
CHATTERS = 2_000
MESSAGES_PER_CHATTER = 5

_timings: list[tuple[str, float]] = []


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    yield
    _timings.append((label, (time.perf_counter() - start) * 1000))


def seed(db, followers: int, chatters: int) -> Channel:
    channel = Channel(
        twitch_user_id=999_999,
        login="bench",
        display_name="Bench",
        scopes=[],
        timezone="UTC",
    )
    db.add(channel)
    db.flush()

    stream = Stream(
        channel_id=channel.id,
        started_at=datetime.now(UTC) - timedelta(days=1),
        ended_at=datetime.now(UTC) - timedelta(days=1, hours=-3),
        status=StreamStatus.READY,
    )
    db.add(stream)
    db.flush()

    now = datetime.now(UTC)
    # chat_messages is partitioned by month and the partition is created on demand
    # in production, so the harness has to make its own.
    ensure_chat_partition(db, (now - timedelta(days=1)).date())
    ensure_chat_partition(db, now.date())
    # Spread account ages and follow dates so the month buckets and age buckets
    # all have work to do, like a real base.
    db.bulk_save_objects(
        [
            Follower(
                channel_id=channel.id,
                twitch_user_id=1_000_000 + n,
                login=f"seguidor{n}",
                followed_at=now - timedelta(days=n % 900),
                display_name=f"Seguidor {n}",
                profile_image_url=f"https://cdn/{n}.png",
                description="bio" if n % 3 else "",
                broadcaster_type=("affiliate" if n % 17 == 0 else None),
                account_created_at=now - timedelta(days=30 + (n % 3000)),
                enriched_at=now,
                last_seen_at=now,
            )
            for n in range(followers)
        ]
    )
    db.bulk_save_objects(
        [
            ChatMessage(
                channel_id=channel.id,
                stream_id=stream.id,
                message_id=f"m{n}-{i}",
                author_id=str(n),
                author_login=f"seguidor{n}",
                text="oi",
                sent_at=now - timedelta(days=1, minutes=i),
            )
            for n in range(chatters)
            for i in range(MESSAGES_PER_CHATTER)
        ]
    )
    db.commit()
    return channel


def main() -> int:
    followers = int(sys.argv[1]) if len(sys.argv) > 1 else FOLLOWERS
    chatters = int(sys.argv[2]) if len(sys.argv) > 2 else CHATTERS

    from apps.api import followers as page
    from core.follower_profiles import build_follower_profiles

    factory = session_factory()
    with factory() as db:
        channel = db.scalar(select(Channel).where(Channel.login == "bench"))
        if channel is None:
            print(f"semeando {followers} seguidores e {chatters} chatters...")
            channel = seed(db, followers, chatters)

        now = datetime.now(UTC)
        with timed("carregar as linhas de follower"):
            rows = list(
                db.scalars(select(Follower).where(Follower.channel_id == channel.id))
            )
        with timed("_chatter_logins"):
            chatter_logins = page._chatter_logins(db, channel.id)
        with timed("_kpis"):
            page._kpis(rows, now, channel.follower_total)
        with timed("_growth"):
            page._growth(rows)
        with timed("_composition"):
            page._composition(rows, chatter_logins, now)
        with timed("recent + notable (ordenar em python)"):
            recent = sorted(rows, key=lambda f: f.followed_at, reverse=True)[:24]
            notable = [
                f for f in rows if f.broadcaster_type in ("affiliate", "partner")
            ]
            notable.sort(key=lambda f: f.followed_at, reverse=True)
            assert recent is not None
        with timed("build_follower_profiles"):
            profiles = build_follower_profiles(db, channel.id, rows)
        with timed("_funnel"):
            page._funnel(profiles)
        with timed("_cohorts"):
            page._cohorts(profiles)
        with timed("_top_value + _loyal_subscribers"):
            page._top_value(profiles)
            page._loyal_subscribers(profiles)
        from core.follower_signals import (
            follow_velocity,
            raid_attribution,
            suspicious_followers,
            topic_to_follows,
        )

        with timed("_signals > raid_attribution"):
            raid_attribution(db, channel.id)
        with timed("_signals > suspicious_followers"):
            suspicious_followers(db, channel.id, now)
        with timed("_signals > follow_velocity"):
            follow_velocity(db, channel.id)
        with timed("_signals > topic_to_follows"):
            topic_to_follows(db, channel.id)
        with timed("_collab"):
            page._collab(db, channel.id)
        with timed("_unfollows"):
            page._unfollows(db, channel.id)

    total = sum(ms for _, ms in _timings)
    print(f"\n{len(rows)} seguidores\n")
    print(f"{'etapa':44}{'ms':>9}{'% do total':>12}")
    for label, ms in sorted(_timings, key=lambda t: t[1], reverse=True):
        print(f"{label:44}{ms:>9.0f}{100 * ms / total:>11.1f}%")
    print(f"{'TOTAL':44}{total:>9.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
