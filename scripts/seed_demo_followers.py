"""Seeds demo channels that each trigger one of the states the followers page has
to handle, so the screens can be checked instead of assumed.

Real data cannot exercise these on demand: nobody's account is guaranteed to have a
bought-looking base or a refused token when you need one.

  demo_grande     41,605 followers spread over years -> the response cap
  demo_comprado   1,200 followers all made inside one 6-month window -> the
                  concentration warning
  demo_token      a refused token -> the reconnect banner
  demo_pequeno    120 followers in one window -> must NOT warn (under the floor)

    DATABASE_URL=... alembic upgrade head
    DATABASE_URL=... python -m scripts.seed_demo_followers
"""

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from core.crypto import create_session_token, encrypt_secret
from core.db import session_factory
from core.follower_sync import TOKEN_ERROR_PREFIX
from core.models import Channel, Follower

BIG = 41_605
BOUGHT = 1_200
SMALL = 120


def _channel(db, login: str, twitch_id: int) -> Channel:
    existing = db.scalar(select(Channel).where(Channel.login == login))
    if existing is not None:
        db.execute(delete(Follower).where(Follower.channel_id == existing.id))
        db.delete(existing)
        db.flush()
    channel = Channel(
        twitch_user_id=twitch_id,
        login=login,
        display_name=login,
        scopes=[],
        timezone="UTC",
        language="pt",
        spoken_language="pt",
        onboarded_at=datetime.now(UTC),
    )
    db.add(channel)
    db.flush()
    return channel


def _followers(channel: Channel, count: int, spread_days: int, now: datetime) -> list:
    """`spread_days` is how wide the account-creation dates are scattered, which is
    the whole difference between an audience that grew and a batch that was made."""
    return [
        Follower(
            channel_id=channel.id,
            twitch_user_id=channel.twitch_user_id * 1_000 + n,
            login=f"{channel.login}_f{n}",
            display_name=f"Seguidor {n}",
            profile_image_url=f"https://cdn/{n}.png",
            description="bio" if n % 3 else "",
            broadcaster_type="affiliate" if n % 23 == 0 else None,
            followed_at=now - timedelta(days=n % 400),
            account_created_at=now - timedelta(days=400 + (n % spread_days)),
            enriched_at=now,
            last_seen_at=now,
        )
        for n in range(count)
    ]


def main() -> int:
    now = datetime.now(UTC)
    factory = session_factory()
    with factory() as db:
        # spread over ~8 years: no six-month window can dominate
        big = _channel(db, "demo_grande", 900_001)
        big.follower_total = BIG
        db.bulk_save_objects(_followers(big, BIG, 2900, now))

        # every account made inside ~5 months: this is what a bought base looks like
        bought = _channel(db, "demo_comprado", 900_002)
        bought.follower_total = BOUGHT
        db.bulk_save_objects(_followers(bought, BOUGHT, 150, now))

        # same shape, too few followers to judge: must stay quiet
        small = _channel(db, "demo_pequeno", 900_003)
        small.follower_total = SMALL
        db.bulk_save_objects(_followers(small, SMALL, 150, now))

        # a token Twitch refuses, which only its owner can fix
        dead = _channel(db, "demo_token", 900_004)
        dead.follower_total = 533
        dead.refresh_token_encrypted = encrypt_secret("revogado")
        dead.follower_sync_error = f"{TOKEN_ERROR_PREFIX}TwitchAuthError: returned 400"
        db.bulk_save_objects(_followers(dead, 533, 2900, now))

        db.commit()

        print("canal | seguidores | cookie de sessao")
        for channel in (big, bought, small, dead):
            total = db.scalar(
                select(Channel.follower_total).where(Channel.id == channel.id)
            )
            print(f"{channel.login} | {total} | {create_session_token(channel.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
