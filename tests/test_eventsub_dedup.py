"""EventSub retry dedup, now in Postgres instead of Valkey.

Twitch retries a webhook until it gets a 2xx, so the same message id arrives
more than once and must only be processed once. This used to be Valkey SET NX;
it is now an INSERT with a primary key, which gives the same atomicity without
making production depend on a Valkey in another region."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.eventsub import DEDUP_TTL_SECONDS, claim_message
from core.models import EventSubMessage


def test_first_claim_wins_and_the_retry_is_dropped(db) -> None:
    assert claim_message(db, "msg-1") is True
    assert claim_message(db, "msg-1") is False, "Twitch retry must be dropped"


def test_different_messages_are_independent(db) -> None:
    assert claim_message(db, "msg-a") is True
    assert claim_message(db, "msg-b") is True


def test_claim_is_visible_immediately(db) -> None:
    # a concurrent retry has to see it, so the claim cannot wait for the caller
    claim_message(db, "msg-visible")
    stored = db.scalars(
        select(EventSubMessage).where(EventSubMessage.message_id == "msg-visible")
    ).all()
    assert len(stored) == 1


def test_prunes_ids_older_than_the_retry_window(db) -> None:
    # the table is a fixed-size window, not a log that grows forever
    old = EventSubMessage(
        message_id="msg-ancient",
        received_at=datetime.now(UTC) - timedelta(seconds=DEDUP_TTL_SECONDS + 60),
    )
    db.add(old)
    db.flush()

    claim_message(db, "msg-new")

    left = set(db.scalars(select(EventSubMessage.message_id)))
    assert "msg-ancient" not in left, "expired ids must be pruned"
    assert "msg-new" in left


def test_an_expired_id_can_be_claimed_again(db) -> None:
    # matches the old TTL behaviour: past the retry window it is a new message
    claim_message(db, "msg-cycle")
    db.execute(select(EventSubMessage).where(EventSubMessage.message_id == "msg-cycle"))
    stored = db.scalars(
        select(EventSubMessage).where(EventSubMessage.message_id == "msg-cycle")
    ).one()
    stored.received_at = datetime.now(UTC) - timedelta(seconds=DEDUP_TTL_SECONDS + 60)
    db.flush()

    assert claim_message(db, "msg-cycle") is True
