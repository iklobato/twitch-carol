"""Build the weekly recap email body for each channel, from data already stored.

Read-only: this sends nothing and writes no database row. It renders each
channel's HTML to a file so the copy can be reviewed before any sending path
exists. A channel with no lives in the week is skipped, not sent an empty
email.

Usage:
    python scripts/weekly_digest.py                     # every channel, last week
    python scripts/weekly_digest.py --login foo         # one channel
    python scripts/weekly_digest.py --week 2026-07-13   # week starting that Monday
    python scripts/weekly_digest.py --out data/digests  # where to write
"""

import argparse
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select

from core.config import get_settings
from core.db import session_factory
from core.models import Channel
from core.weekly import build_week, channel_zone, last_week_bounds, render_html

DEFAULT_OUT = Path("data/digests")


def _week_bounds(channel: Channel, week: date | None) -> tuple[datetime, datetime]:
    zone = channel_zone(channel)
    if week is None:
        return last_week_bounds(datetime.now(UTC), zone)
    start = datetime.combine(week, time.min, tzinfo=zone)
    return start, start + timedelta(days=7)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", help="restrict to one channel login")
    parser.add_argument(
        "--week", type=date.fromisoformat, help="Monday the week starts on (YYYY-MM-DD)"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    dashboard_url = get_settings().public_base_url

    with session_factory()() as db:
        query = select(Channel)
        if args.login:
            query = query.where(Channel.login == args.login)
        channels = db.scalars(query).all()

        written = 0
        for channel in channels:
            start, end = _week_bounds(channel, args.week)
            digest = build_week(db, channel, start, end)
            if digest.is_empty:
                print(f"{channel.login}: no lives in {start:%d/%m} - nothing to send")
                continue
            path = args.out / f"{channel.login}-{start:%Y-%m-%d}.html"
            path.write_text(render_html(digest, dashboard_url), encoding="utf-8")
            written += 1
            print(f"{channel.login}: {len(digest.lives)} live(s) -> {path}")

    print(f"done: {written} digest(s) of {len(channels)} channel(s), nothing sent")


if __name__ == "__main__":
    main()
