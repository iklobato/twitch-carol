"""External tips ingestion: dedup + credential storage."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.integrations import tips as tips_module
from core.integrations.streamelements import RemoteTip
from core.integrations.tips import (
    set_streamelements_credentials,
    sync_streamelements_tips,
)
from core.models import ExternalTip
from tests.factories import make_channel


def _tip(external_id: str, amount: float) -> RemoteTip:
    return RemoteTip(
        external_id=external_id,
        amount=amount,
        currency="USD",
        tipper="bob",
        message=None,
        tipped_at=datetime(2026, 7, 17, tzinfo=UTC),
    )


def _stored(db: Session, channel_id: int) -> set[str]:
    return set(
        db.scalars(
            select(ExternalTip.external_id).where(ExternalTip.channel_id == channel_id)
        )
    )


def test_sync_stores_and_dedups(db: Session, monkeypatch) -> None:
    channel = make_channel(db)
    set_streamelements_credentials(db, channel, "acct-9", "the-jwt")
    assert channel.streamelements_account_id == "acct-9"
    assert channel.streamelements_jwt_encrypted is not None  # stored encrypted

    monkeypatch.setattr(
        tips_module, "fetch_tips", lambda *a, **k: [_tip("t1", 5.0), _tip("t2", 10.0)]
    )
    assert sync_streamelements_tips(db, channel) == 2
    assert _stored(db, channel.id) == {"t1", "t2"}

    # a later sync returns an already-stored tip plus a new one: only the new one lands
    monkeypatch.setattr(
        tips_module, "fetch_tips", lambda *a, **k: [_tip("t2", 10.0), _tip("t3", 3.0)]
    )
    assert sync_streamelements_tips(db, channel) == 1
    assert _stored(db, channel.id) == {"t1", "t2", "t3"}


def test_sync_is_noop_without_credentials(db: Session) -> None:
    channel = make_channel(db, login="nocreds")
    assert sync_streamelements_tips(db, channel) == 0
