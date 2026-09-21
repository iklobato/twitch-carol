"""scripts.send_email_digests: per-channel send-hour gating and the
reserve-before-send idempotency that stops a re-run from emailing twice.

No money events in any fixture here, so core.digest_insights.build_digest_facts
returns no facts and the LLM is never actually called: these tests are about
gating/idempotency, not the insights content (covered by test_digest_insights.py).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import scripts.send_email_digests as sed
from core.config import get_settings
from core.digest import last_period_bounds
from core.mailer import MailerError, MailerUncertain
from core.models import DigestPeriod, EmailDigestLog
from tests.factories import add_event, make_channel, make_stream

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env", "resend_env")

# 08:00 UTC = the default send hour. Anchored to TODAY, not a fixed date:
# make_stream places a live relative to the real clock, so a hardcoded date
# silently walks out of the period window as the calendar moves and every
# test here starts reporting "skipped (no lives)".
NOW = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)


class _FakeBackend:
    model_name = "fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        raise AssertionError("no facts in these fixtures, the LLM must not be called")


class _FakeMailer:
    """Records every `to` it was sent to and returns a fixed message id."""

    def __init__(self, message_id: str = "msg") -> None:
        self.message_id = message_id
        self.sent_to: list[str] = []

    def __call__(self, to: str, subject: str, html: str, unsubscribe_url: str) -> str:
        self.sent_to.append(to)
        return self.message_id


def _forbidden_send(*args: object, **kwargs: object) -> str:
    raise AssertionError("must not send")


@pytest.fixture(autouse=True)
def _fake_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sed, "get_llm_backend", lambda: _FakeBackend())


def _channel_with_a_live_in_last_week(db: Session, **channel_kwargs):
    channel = make_channel(db, **channel_kwargs)
    zone = ZoneInfo("UTC")
    start, _ = last_period_bounds(DigestPeriod.WEEKLY, NOW, zone)
    live_at = start + timedelta(days=1)
    stream = make_stream(
        db, channel, started_minutes_ago=int((NOW - live_at).total_seconds() / 60)
    )
    add_event(db, stream, "channel.follow", offset_seconds=60)
    return channel


def _log_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(EmailDigestLog)) or 0


def test_skips_a_channel_not_due_yet_by_its_own_local_hour(db: Session) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="notdue")
    channel.email = "notdue@example.com"

    off_hour = NOW.replace(hour=(get_settings().digest_send_hour + 1) % 24)
    results = sed.run(
        db, [DigestPeriod.WEEKLY], None, off_hour, dry_run=False, to_override=None
    )

    assert results[f"{channel.login}/weekly"] == "not due yet"
    assert _log_count(db) == 0


def test_sends_and_a_second_run_for_the_same_window_is_a_noop(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="sender")
    channel.email = "sender@example.com"
    mailer = _FakeMailer("msg_1")
    monkeypatch.setattr(sed, "send_email", mailer)

    first = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )
    second = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )

    assert first[f"{channel.login}/weekly"] == "sent (msg_1)"
    assert second[f"{channel.login}/weekly"] == "skipped (already sent)"
    # the second run never called send_email again
    assert mailer.sent_to == ["sender@example.com"]
    assert _log_count(db) == 1
    log = db.scalars(select(EmailDigestLog)).one()
    assert log.sent_at is not None
    assert log.provider_message_id == "msg_1"


def test_channel_with_the_period_flag_off_is_excluded(db: Session) -> None:
    off = _channel_with_a_live_in_last_week(db, login="optedout")
    off.email = "optedout@example.com"
    off.digest_weekly = False
    on = _channel_with_a_live_in_last_week(db, login="optedin")
    on.email = "optedin@example.com"

    results = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=True, to_override=None
    )

    assert f"{off.login}/weekly" not in results
    assert results[f"{on.login}/weekly"] == "would send"


def test_channel_without_an_email_is_excluded_unless_a_recipient_is_forced(
    db: Session,
) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="noemail")
    assert channel.email is None

    without_override = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=True, to_override=None
    )
    with_override = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=True, to_override="me@example.com"
    )

    assert f"{channel.login}/weekly" not in without_override
    assert with_override[f"{channel.login}/weekly"] == "would send"


def test_to_override_wins_over_the_channels_own_email(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="override")
    channel.email = "real@example.com"
    mailer = _FakeMailer("msg_2")
    monkeypatch.setattr(sed, "send_email", mailer)

    sed.run(
        db,
        [DigestPeriod.WEEKLY],
        None,
        NOW,
        dry_run=False,
        to_override="override@example.com",
    )

    assert mailer.sent_to == ["override@example.com"]


def test_dry_run_never_reserves_or_sends(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="dryrun")
    channel.email = "dryrun@example.com"
    monkeypatch.setattr(sed, "send_email", _forbidden_send)

    results = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=True, to_override=None
    )

    assert results[f"{channel.login}/weekly"] == "would send"
    assert _log_count(db) == 0


def test_a_failed_send_releases_the_reservation_so_the_next_run_retries(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = _channel_with_a_live_in_last_week(db, login="retry")
    channel.email = "retry@example.com"
    # Committed, same as the real script: a channel's own row is already
    # committed by the time this script runs, in an unrelated transaction.
    # A rollback triggered by a failed send must only undo the reservation,
    # never data the channel itself already saved.
    db.commit()

    def _fail(to: str, subject: str, html: str, unsubscribe_url: str) -> str:
        raise MailerError("resend is down")

    monkeypatch.setattr(sed, "send_email", _fail)

    first = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )
    assert first[f"{channel.login}/weekly"] == "failed"
    assert _log_count(db) == 0  # the reservation was rolled back

    mailer = _FakeMailer("msg_3")
    monkeypatch.setattr(sed, "send_email", mailer)
    second = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )
    assert second[f"{channel.login}/weekly"] == "sent (msg_3)"
    assert mailer.sent_to == ["retry@example.com"]


def test_a_send_with_no_answer_keeps_the_reservation_so_it_is_never_resent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is not a failure: Resend may already hold the email. The
    reservation stays so the next hourly run cannot send it a second time."""
    channel = _channel_with_a_live_in_last_week(db, login="uncertain")
    channel.email = "uncertain@example.com"
    db.commit()

    def _timeout(to: str, subject: str, html: str, unsubscribe_url: str) -> str:
        raise MailerUncertain("resend did not answer")

    monkeypatch.setattr(sed, "send_email", _timeout)

    first = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )
    assert first[f"{channel.login}/weekly"] == "uncertain (not retried)"
    assert _log_count(db) == 1

    reservation = db.scalar(select(EmailDigestLog))
    assert reservation is not None
    assert reservation.sent_at is None  # nothing is claimed as delivered

    mailer = _FakeMailer("msg_dup")
    monkeypatch.setattr(sed, "send_email", mailer)
    second = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )
    assert second[f"{channel.login}/weekly"] == "skipped (already sent)"
    assert mailer.sent_to == []


def test_a_channel_with_no_lives_in_the_period_is_skipped_without_reserving(
    db: Session,
) -> None:
    channel = make_channel(db, login="quiet")
    channel.email = "quiet@example.com"

    results = sed.run(
        db, [DigestPeriod.WEEKLY], None, NOW, dry_run=False, to_override=None
    )

    assert results[f"{channel.login}/weekly"] == "skipped (no lives)"
    assert _log_count(db) == 0
