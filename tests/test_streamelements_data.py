"""StreamElements loyalty + merch connectors (pure HTTP client)."""

import httpx
import pytest

from core.integrations.streamelements import (
    StreamElementsError,
    fetch_loyalty_top,
    fetch_merch,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_loyalty_top_parses_envelope_and_skips_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/points/acct/top" in str(request.url)
        assert request.headers.get("Authorization") == "oAuth tok"  # OAuth scheme
        return httpx.Response(
            200,
            json={
                "users": [
                    {"username": "alice", "points": 500},
                    {"username": "bob", "points": 100},
                    {"points": 50},  # no username -> skipped
                ]
            },
        )

    entries = fetch_loyalty_top("acct", "oAuth tok", client=_client(handler))

    assert [e.username for e in entries] == ["alice", "bob"]
    assert entries[0].points == 500


def test_fetch_loyalty_top_accepts_bare_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"username": "x", "points": 1}])

    assert fetch_loyalty_top("a", "t", client=_client(handler))[0].username == "x"


def test_fetch_loyalty_top_raises_on_error() -> None:
    with pytest.raises(StreamElementsError, match="403"):
        fetch_loyalty_top(
            "a", "t", client=_client(lambda r: httpx.Response(403, json={}))
        )


def test_fetch_merch_keeps_only_merch_and_skips_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/activities/acct" in str(request.url)
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "_id": "m1",
                        "type": "merch",
                        "createdAt": "2026-07-17T10:00:00.000Z",
                        "data": {"amount": 25.0, "currency": "USD", "username": "bob"},
                    },
                    {  # a tip, not merch -> Twitch/tips path owns it, skip here
                        "_id": "t1",
                        "type": "tip",
                        "createdAt": "2026-07-17T11:00:00.000Z",
                        "data": {"amount": 5.0},
                    },
                    {  # merch but no amount -> skipped
                        "_id": "m2",
                        "type": "merch",
                        "createdAt": "2026-07-17T09:00:00.000Z",
                        "data": {},
                    },
                ]
            },
        )

    sales = fetch_merch("acct", "tok", client=_client(handler))

    assert len(sales) == 1
    assert sales[0].external_id == "m1"
    assert sales[0].amount == 25.0
    assert sales[0].currency == "USD"
    assert sales[0].actor == "bob"
