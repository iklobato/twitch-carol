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
    get_videos,
    iter_followers,
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


def test_iter_followers_paginates_until_cursor_ends() -> None:
    pages = [
        {
            "data": [
                {
                    "user_id": "1",
                    "user_login": "a",
                    "followed_at": "2026-01-01T00:00:00Z",
                }
            ],
            "pagination": {"cursor": "next"},
        },
        {
            "data": [
                {
                    "user_id": "2",
                    "user_login": "b",
                    "followed_at": "2026-02-01T00:00:00Z",
                }
            ],
            "pagination": {},
        },
    ]
    seen_cursors = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        seen_cursors.append(params.get("after", [None])[0])
        return httpx.Response(200, json=pages[len(seen_cursors) - 1])

    followers = list(iter_followers(999, "tok", client=_mock_client(handler)))

    assert [f.user_login for f in followers] == ["a", "b"]
    assert seen_cursors == [None, "next"]  # second request carried the cursor


def test_get_videos_parses_duration_to_seconds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "v1",
                        "title": "Deploy day",
                        "created_at": "2026-03-01T18:00:00Z",
                        "duration": "1h2m3s",
                        "view_count": "150",
                        "url": "https://twitch.tv/videos/v1",
                    }
                ]
            },
        )

    videos = get_videos(999, "tok", client=_mock_client(handler))

    assert len(videos) == 1
    assert videos[0].duration_seconds == 3723  # 1h + 2m + 3s
    assert videos[0].view_count == 150


def test_error_messages_never_contain_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid token"})

    with pytest.raises(TwitchAuthError) as exc_info:
        get_user("secret-access-token", client=_mock_client(handler))
    assert "secret-access-token" not in json.dumps(str(exc_info.value))
