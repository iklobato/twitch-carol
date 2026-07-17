"""Populate the stream-records history for lives captured before the feature
existed. New lives set records automatically when analyzed; this seeds the
past ones. Idempotent: re-running rebuilds the same rows.

Usage:
    python scripts/backfill_records.py              # every channel
    python scripts/backfill_records.py --login foo  # one channel
"""

import argparse

from sqlalchemy import select

from core.db import session_factory
from core.models import Channel
from core.records import backfill_records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", help="restrict to one channel login")
    args = parser.parse_args()

    with session_factory()() as db:
        query = select(Channel)
        if args.login:
            query = query.where(Channel.login == args.login)
        channels = db.scalars(query).all()
        total = 0
        for channel in channels:
            written = backfill_records(db, channel.id)
            total += written
            print(f"channel {channel.login}: {written} record rows")
        db.commit()
        print(f"done: {total} record rows across {len(channels)} channel(s)")


if __name__ == "__main__":
    main()
