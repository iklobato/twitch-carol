"""Put failed streams back on the queue, at the step that actually failed.

For streams that died because of an outage and not because of their data: the
transcription API out of credit, an expired token, a worker OOM. Both the
transcribe and the analyze pipelines wipe their own rows before rewriting
them, so a rerun replaces the old result rather than duplicating it.

Dry run by default: nothing is written without --apply.

Usage:
    python scripts/requeue_failed_streams.py             # every failed stream
    python scripts/requeue_failed_streams.py 65 66 67    # only these
    python scripts/requeue_failed_streams.py --apply     # actually commit
"""

import argparse

from core.db import session_factory
from core.queues import requeue_failed_streams


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stream_ids",
        nargs="*",
        type=int,
        help="stream ids to requeue (default: every failed stream)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="commit; without it nothing is written"
    )
    args = parser.parse_args()

    with session_factory()() as db:
        requeued = requeue_failed_streams(db, args.stream_ids or None)
        for stream_id, job_type in requeued:
            print(f"stream {stream_id}: requeued at {job_type}")
        if args.apply:
            db.commit()
            print(f"{len(requeued)} stream(s) requeued")
        else:
            db.rollback()
            print(f"dry run: {len(requeued)} stream(s) would be requeued, pass --apply")


if __name__ == "__main__":
    main()
