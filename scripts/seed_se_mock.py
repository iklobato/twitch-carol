"""Seed mock StreamElements data (tips, merch, loyalty leaderboard) for a
channel so the finance UI can be exercised locally without a real StreamElements
connection. Idempotent: re-running wipes the prior mock rows and reseeds.

Usage:
    python scripts/seed_se_mock.py --login foo
"""

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from core.db import session_factory
from core.models import Channel, ExternalTip, LoyaltyEntry

SOURCE_MOCK = "mock"
MOCK_TIPS = [("alice", 25.0), ("bob", 10.0), ("carol", 50.0)]
MOCK_MERCH = [("dave", 35.0), ("alice", 20.0)]
MOCK_LOYALTY = [("alice", 9000), ("bob", 4200), ("carol", 3100), ("erin", 1500)]


def _tip(channel_id: int, kind: str, i: int, who: str, amount: float, when: datetime):
    return ExternalTip(
        channel_id=channel_id,
        source=SOURCE_MOCK,
        # external_id is globally unique (source, external_id), so namespace it
        # per channel: fixed ids would collide across seeded channels.
        external_id=f"mock-{channel_id}-{kind}-{i}",
        kind=kind,
        amount=amount,
        currency="USD",
        tipper=who,
        message="valeu!" if kind == "tip" else None,
        tipped_at=when,
    )


def seed(login: str) -> None:
    with session_factory()() as db:
        channel = db.scalar(select(Channel).where(Channel.login == login))
        if channel is None:
            raise SystemExit(f"channel '{login}' not found")
        db.execute(
            delete(ExternalTip).where(
                ExternalTip.channel_id == channel.id,
                ExternalTip.source == SOURCE_MOCK,
            )
        )
        db.execute(delete(LoyaltyEntry).where(LoyaltyEntry.channel_id == channel.id))
        now = datetime.now(UTC)
        for i, (who, amount) in enumerate(MOCK_TIPS):
            db.add(_tip(channel.id, "tip", i, who, amount, now - timedelta(days=i)))
        for i, (who, amount) in enumerate(MOCK_MERCH):
            db.add(_tip(channel.id, "merch", i, who, amount, now - timedelta(days=i)))
        for rank, (who, points) in enumerate(MOCK_LOYALTY, start=1):
            db.add(
                LoyaltyEntry(
                    channel_id=channel.id,
                    username=who,
                    points=points,
                    rank=rank,
                    synced_at=now,
                )
            )
        db.commit()
        print(
            f"seeded {len(MOCK_TIPS)} tips, {len(MOCK_MERCH)} merch, "
            f"{len(MOCK_LOYALTY)} loyalty for {login}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", required=True, help="channel login to seed")
    args = parser.parse_args()
    seed(args.login)


if __name__ == "__main__":
    main()
