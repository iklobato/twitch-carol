"""StreamElements OAuth connector (pure HTTP client)."""

from types import SimpleNamespace

import httpx
import pytest

import core.integrations.streamelements as se
from core.integrations.streamelements import (
    StreamElementsError,
    build_authorize_url,
    exchange_code,
    fetch_channel_id,
    refresh_access_token,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _se_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        se,
        "get_settings",
        lambda: SimpleNamespace(
            streamelements_client_id="cid",
            streamelements_client_secret="csecret",
            public_base_url="https://app.test",
        ),
    )


def test_build_authorize_url_has_all_params() -> None:
    url = build_authorize_url("st8")
    params = httpx.QueryParams(url.split("?", 1)[1])

    assert url.startswith(se.OAUTH_AUTHORIZE)
    assert params["client_id"] == "cid"
    assert params["response_type"] == "code"
    assert params["state"] == "st8"
    assert params["scope"] == " ".join(se.SE_SCOPES)
    assert params["redirect_uri"] == "https://app.test" + se.CALLBACK_PATH


def test_exchange_code_posts_grant_and_parses_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = httpx.QueryParams(request.content.decode())
        return httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        )

    token = exchange_code("the-code", client=_client(handler))

    assert token.access_token == "at"
    assert token.refresh_token == "rt"
    assert token.expires_in == 3600
    assert seen["url"] == se.OAUTH_TOKEN
    form = seen["form"]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["client_id"] == "cid"
    assert form["client_secret"] == "csecret"
    assert form["redirect_uri"] == "https://app.test" + se.CALLBACK_PATH


def test_refresh_access_token_uses_refresh_grant() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = httpx.QueryParams(request.content.decode())
        return httpx.Response(200, json={"access_token": "at2", "expires_in": 60})

    token = refresh_access_token("old-refresh", client=_client(handler))

    assert token.access_token == "at2"
    assert token.refresh_token is None  # response omitted it
    form = seen["form"]
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "old-refresh"


def test_fetch_channel_id_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer at"
        assert "/channels/me" in str(request.url)
        return httpx.Response(200, json={"_id": "chan-1", "displayName": "x"})

    assert fetch_channel_id("at", client=_client(handler)) == "chan-1"


def test_fetch_channel_id_raises_when_id_missing() -> None:
    with pytest.raises(StreamElementsError, match="_id"):
        fetch_channel_id("at", client=_client(lambda r: httpx.Response(200, json={})))
