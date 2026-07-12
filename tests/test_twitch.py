import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from core.twitch import (
    OAUTH_SCOPES,
    TwitchAuthError,
    build_authorize_url,
    exchange_code,
    get_user,
)

pytestmark = pytest.mark.usefixtures("twitch_env")

GRANT_JSON = {
    "access_token": "new-access",
    "refresh_token": "new-refresh",
    "expires_in": 14400,
    "scope": ["bits:read"],
}


def test_build_authorize_url() -> None:
    url = build_authorize_url("some-state")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.hostname == "id.twitch.tv"
    assert params["client_id"] == ["test-client-id"]
    assert params["state"] == ["some-state"]
    assert params["redirect_uri"] == ["http://localhost:8080/auth/callback"]
    assert params["scope"] == [" ".join(OAUTH_SCOPES)]


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exchange_code_posts_grant_and_parses_response() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json=GRANT_JSON)

    grant = exchange_code("the-code", client=_mock_client(handler))

    assert seen["grant_type"] == ["authorization_code"]
    assert seen["code"] == ["the-code"]
    assert seen["client_secret"] == ["test-client-secret"]
    assert seen["redirect_uri"] == ["http://localhost:8080/auth/callback"]
    assert grant.access_token == "new-access"
    assert grant.refresh_token == "new-refresh"


def test_exchange_code_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "denied"})

    with pytest.raises(TwitchAuthError, match="403"):
        exchange_code("bad-code", client=_mock_client(handler))


def test_get_user_parses_helix_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer some-access"
        assert request.headers["Client-Id"] == "test-client-id"
        return httpx.Response(
            200,
            json={"data": [{"id": "123", "login": "henry", "display_name": "Henry"}]},
        )

    user = get_user("some-access", client=_mock_client(handler))
    assert user.id == "123"
    assert user.login == "henry"


def test_get_user_empty_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with pytest.raises(TwitchAuthError, match="no user"):
        get_user("some-access", client=_mock_client(handler))


def test_error_messages_never_contain_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid token"})

    with pytest.raises(TwitchAuthError) as exc_info:
        get_user("secret-access-token", client=_mock_client(handler))
    assert "secret-access-token" not in json.dumps(str(exc_info.value))
