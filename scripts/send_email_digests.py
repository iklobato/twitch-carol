"""Send the weekly/monthly email digest to channels that opted in.

Meant to run hourly (scheduled job). For each eligible channel, sends the
last complete period's digest once the channel's OWN local clock reaches
settings.digest_send_hour. A period's content stays the same across every
hourly run until the period rolls over, so what actually stops a duplicate
send is EmailDigestLog's unique constraint on (channel, period,
period_start), not this hour check: the check only decides when in the day
to try.

Usage:
    python scripts/send_email_digests.py                    # every eligible channel, both periods
    python scripts/send_email_digests.py --channel foo
    python scripts/send_email_digests.py --period weekly
    python scripts/send_email_digests.py --now 2026-09-21T08:00:00+00:00
    python scripts/send_email_digests.py --dry-run
    python scripts/send_email_digests.py --channel foo --to me@example.com
"""

import argparse
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import get_settings
from core.crypto import create_unsubscribe_token
from core.db import session_factory
from core.digest import (
    build_last_period,
    channel_zone,
    digest_subject,
    render_html,
    with_insights,
)
from core.digest_insights import build_digest_facts, generate_digest_insights
from core.llm import TokenBudget, get_llm_backend
from core.logging_setup import setup_logging
from core.mailer import MailerError, send_email
from core.models import Channel, DigestPeriod, EmailDigestLog

logger = logging.getLogger(__name__)

PERIOD_FLAGS = {
    DigestPeriod.WEEKLY: "digest_weekly",
    DigestPeriod.MONTHLY: "digest_monthly",
}


def _eligible_channels(
    db: Session, period: DigestPeriod, login: str | None, require_email: bool
) -> list[Channel]:
    flag = getattr(Channel, PERIOD_FLAGS[period])
    query = select(Channel).where(flag.is_(True))
    if require_email:
        query = query.where(Channel.email.is_not(None))
    if login:
        query = query.where(Channel.login == login)
    return list(db.scalars(query).all())


def _due_now(channel: Channel, now: datetime, send_hour: int) -> bool:
    """True once the channel's own local clock reaches the configured hour."""
    return now.astimezone(channel_zone(channel)).hour == send_hour


def _reserve(
    db: Session, channel: Channel, period: DigestPeriod, start: datetime, end: datetime
) -> EmailDigestLog | None:
    """Insert-before-send. None means another run already reserved (or sent)
    this exact channel+period+window, so the caller skips it."""
    log = EmailDigestLog(
        channel_id=channel.id, period=period, period_start=start, period_end=end
    )
    db.add(log)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    return log


def _unsubscribe_url(base_url: str, channel_id: int, period: DigestPeriod) -> str:
    token = create_unsubscribe_token(channel_id)
    return f"{base_url}/api/digest/unsubscribe?t={token}&period={period.value}"


def _send_one(
    db: Session,
    channel: Channel,
    period: DigestPeriod,
    now: datetime,
    to_override: str | None,
) -> str:
    """Builds, reserves and sends one channel's digest. Returns a short
    status word for the run summary."""
    settings = get_settings()
    digest = build_last_period(db, channel, period, now)
    if digest.is_empty:
        return "skipped (no lives)"

    reservation = _reserve(db, channel, period, digest.start, digest.end)
    if reservation is None:
        return "skipped (already sent)"

    try:
        backend = get_llm_backend()
        budget = TokenBudget(
            backend, settings.llm_max_input_tokens, settings.llm_max_output_tokens
        )
        facts = build_digest_facts(digest)
        insights = generate_digest_insights(digest, facts, backend, budget)
        digest = with_insights(digest, insights)

        unsubscribe_url = _unsubscribe_url(settings.public_base_url, channel.id, period)
        html = render_html(digest, settings.public_base_url, unsubscribe_url)
        to = to_override or settings.digest_recipient_override or channel.email
        if not to:
            db.rollback()
            return "skipped (no recipient)"
        message_id = send_email(to, digest_subject(digest), html, unsubscribe_url)
    except MailerError:
        db.rollback()
        logger.exception(
            "digest send failed", extra={"login": channel.login, "period": period.value}
        )
        return "failed"

    reservation.sent_at = datetime.now(UTC)
    reservation.provider_message_id = message_id
    db.commit()
    return f"sent ({message_id})"


def run(
    db: Session,
    periods: list[DigestPeriod],
    login: str | None,
    now: datetime,
    dry_run: bool,
    to_override: str | None,
) -> dict[str, str]:
    settings = get_settings()
    require_email = not (to_override or settings.digest_recipient_override)
    results: dict[str, str] = {}
    for period in periods:
        for channel in _eligible_channels(db, period, login, require_email):
            key = f"{channel.login}/{period.value}"
            if not _due_now(channel, now, settings.digest_send_hour):
                results[key] = "not due yet"
                continue
            if dry_run:
                digest = build_last_period(db, channel, period, now)
                results[key] = "empty" if digest.is_empty else "would send"
                continue
            results[key] = _send_one(db, channel, period, now, to_override)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", help="restrict to one channel login")
    parser.add_argument(
        "--period",
        choices=[p.value for p in DigestPeriod],
        help="restrict to one period",
    )
    parser.add_argument(
        "--now", help="ISO datetime to treat as the current time (testing)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would send, without sending"
    )
    parser.add_argument("--to", help="send every digest to this address instead")
    args = parser.parse_args()

    setup_logging()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    periods = [DigestPeriod(args.period)] if args.period else list(DigestPeriod)

    with session_factory()() as db:
        results = run(db, periods, args.channel, now, args.dry_run, args.to)

    for key, status in results.items():
        print(f"{key}: {status}")
    print(f"done: {len(results)} channel/period combination(s)")


if __name__ == "__main__":
    main()
