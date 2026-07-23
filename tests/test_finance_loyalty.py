"""Merch + loyalty ingestion and the finance endpoints that expose them."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

import core.integrations.tips as tips_module
from core.integrations.streamelements import RemoteLoyaltyEntry, RemoteRevenue, SEToken
from core.integrations.tips import (
    set_streamelements_oauth,
    sync_streamelements_loyalty,
    sync_streamelements_merch,
)
from core.models import ExternalTip, LoyaltyEntry
from tests.conftest import login_as
from tests.factories import make_channel

WHEN = datetime(2026, 7, 1, tzinfo=UTC)


def _connect(db: Session, channel) -> None:
    set_streamelements_oauth(
        db,
        channel,
        "acct",
        SEToken(access_token="at", refresh_token="rt", expires_in=3600),
    )


def _ext_tip(channel_id: int, external_id: str, kind: str, amount: float, who: str):
    return ExternalTip(
        channel_id=channel_id,
        source="streamelements",
        external_id=external_id,
        kind=kind,
        amount=amount,
        currency="USD",
        tipper=who,
        message=None,
        tipped_at=WHEN,
    )


def test_sync_merch_stores_as_merch_kind_and_dedups(db: Session, monkeypatch) -> None:
    channel = make_channel(db, login="merchch")
    _connect(db, channel)
    sale = RemoteRevenue(
        external_id="m1", amount=25.0, currency="USD", actor="bob", occurred_at=WHEN
    )
    monkeypatch.setattr(tips_module, "fetch_merch", lambda *a, **k: [sale])

    assert sync_streamelements_merch(db, channel) == 1
    rows = db.scalars(
        select(ExternalTip).where(
            ExternalTip.channel_id == channel.id, ExternalTip.kind == "merch"
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].amount == 25.0
    assert rows[0].tipper == "bob"

    assert sync_streamelements_merch(db, channel) == 0  # same sale -> deduped


def test_sync_loyalty_replaces_snapshot(db: Session, monkeypatch) -> None:
    channel = make_channel(db, login="loych")
    _connect(db, channel)
    monkeypatch.setattr(
        tips_module,
        "fetch_loyalty_top",
        lambda *a, **k: [
            RemoteLoyaltyEntry(username="alice", points=500),
            RemoteLoyaltyEntry(username="bob", points=100),
        ],
    )
    assert sync_streamelements_loyalty(db, channel) == 2
    ranked = db.scalars(
        select(LoyaltyEntry)
        .where(LoyaltyEntry.channel_id == channel.id)
        .order_by(LoyaltyEntry.rank)
    ).all()
    assert [(r.username, r.rank) for r in ranked] == [("alice", 1), ("bob", 2)]

    # a fresh snapshot wipes the old one (current standings, not an event log)
    monkeypatch.setattr(
        tips_module,
        "fetch_loyalty_top",
        lambda *a, **k: [RemoteLoyaltyEntry(username="carol", points=999)],
    )
    assert sync_streamelements_loyalty(db, channel) == 1
    remaining = db.scalars(
        select(LoyaltyEntry).where(LoyaltyEntry.channel_id == channel.id)
    ).all()
    assert [r.username for r in remaining] == ["carol"]


def test_finance_overview_splits_tips_and_merch(api_client, db: Session) -> None:
    channel = make_channel(db, login="splitch")
    login_as(api_client, channel)
    db.add_all(
        [
            _ext_tip(channel.id, "t1", "tip", 10.0, "a"),
            _ext_tip(channel.id, "m1", "merch", 25.0, "b"),
        ]
    )
    db.commit()

    body = api_client.get("/api/finance?period=all").json()

    assert body["tips_usd"] == 10.0
    assert body["merch_usd"] == 25.0
    assert body["total_revenue_usd"] == 35.0  # no Twitch events: 0 + 10 + 25


def test_loyalty_endpoint_returns_ranked(api_client, db: Session) -> None:
    channel = make_channel(db, login="loyendp")
    login_as(api_client, channel)
    db.add_all(
        [
            LoyaltyEntry(
                channel_id=channel.id,
                username="alice",
                points=500,
                rank=1,
                synced_at=WHEN,
            ),
            LoyaltyEntry(
                channel_id=channel.id,
                username="bob",
                points=100,
                rank=2,
                synced_at=WHEN,
            ),
        ]
    )
    db.commit()

    body = api_client.get("/api/finance/loyalty").json()

    assert [row["username"] for row in body] == ["alice", "bob"]
    assert body[0]["points"] == 500


def test_top_people_merges_tips_and_loyalty(api_client, db: Session) -> None:
    channel = make_channel(db, login="people")
    login_as(api_client, channel)
    db.add(_ext_tip(channel.id, "t1", "tip", 50.0, "Alice"))
    db.add(
        LoyaltyEntry(
            channel_id=channel.id, username="alice", points=900, rank=1, synced_at=WHEN
        )
    )
    db.add(
        LoyaltyEntry(
            channel_id=channel.id, username="bob", points=300, rank=2, synced_at=WHEN
        )
    )
    db.commit()

    body = api_client.get("/api/finance/top-people").json()

    assert body[0]["name"] == "Alice"  # tips rank it first
    assert body[0]["tips_usd"] == 50.0
    assert body[0]["loyalty_points"] == 900  # merged by name, case-insensitive
    assert body[1]["name"] == "bob"
    assert body[1]["tips_usd"] == 0.0
    assert body[1]["loyalty_points"] == 300
