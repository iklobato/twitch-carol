"""Top supporters: external tips aggregated per tipper."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.models import ExternalTip
from tests.conftest import login_as
from tests.factories import make_channel


def _tip(
    channel_id: int,
    tipper: str | None,
    amount: float,
    external_id: str,
    when: datetime,
) -> ExternalTip:
    return ExternalTip(
        channel_id=channel_id,
        source="streamelements",
        external_id=external_id,
        amount=amount,
        currency="USD",
        tipper=tipper,
        message=None,
        tipped_at=when,
    )


def test_top_supporters_ranked_and_aggregated(api_client, db: Session) -> None:
    channel = make_channel(db)
    login_as(api_client, channel)
    db.add_all(
        [
            _tip(channel.id, "alice", 5.0, "a1", datetime(2026, 7, 1, tzinfo=UTC)),
            _tip(channel.id, "alice", 20.0, "a2", datetime(2026, 7, 5, tzinfo=UTC)),
            _tip(channel.id, "bob", 10.0, "b1", datetime(2026, 7, 2, tzinfo=UTC)),
            _tip(channel.id, None, 99.0, "anon", datetime(2026, 7, 3, tzinfo=UTC)),
        ]
    )
    db.commit()

    body = api_client.get("/api/finance/supporters").json()

    assert [s["tipper"] for s in body] == ["alice", "bob"]  # 25 vs 10, anon excluded
    assert body[0]["total"] == 25.0
    assert body[0]["tips_count"] == 2
    assert body[0]["currency"] == "USD"
    assert body[0]["last_tipped_at"].startswith("2026-07-05")


def test_top_supporters_empty_without_tips(api_client, db: Session) -> None:
    channel = make_channel(db, login="notips")
    login_as(api_client, channel)

    assert api_client.get("/api/finance/supporters").json() == []
