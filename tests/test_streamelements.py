"""StreamElements tips connector (pure HTTP client)."""

import httpx
import pytest

from core.integrations.streamelements import RemoteTip, StreamElementsError, fetch_tips


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_tips_parses_donations_and_skips_malformed() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "_id": "a1",
                        "createdAt": "2026-07-17T10:00:00.000Z",
                        "donation": {
                            "amount": 5.0,
                            "currency": "USD",
                            "user": {"username": "bob"},
                            "message": "gg",
                        },
                    },
                    {
                        "_id": "a2",
                        "createdAt": "2026-07-17T11:00:00.000Z",
                        "donation": {"amount": 10, "currency": "BRL", "user": {}},
                    },
                    {"createdAt": "2026-07-17T12:00:00.000Z", "donation": {}},
                ]
            },
        )

    tips = fetch_tips("acct-1", "jwt-x", client=_client(handler))

    assert len(tips) == 2  # the third doc (no _id/amount) is skipped
    assert all(isinstance(t, RemoteTip) for t in tips)
    assert tips[0].external_id == "a1"
    assert tips[0].amount == 5.0
    assert tips[0].tipper == "bob"
    assert tips[1].currency == "BRL"
    assert tips[1].tipper is None  # no username in the payload
    assert "/tips/acct-1" in str(seen["url"])
    assert seen["auth"] == "Bearer jwt-x"


def test_fetch_tips_raises_on_error() -> None:
    with pytest.raises(StreamElementsError, match="401"):
        fetch_tips("a", "j", client=_client(lambda r: httpx.Response(401, json={})))
