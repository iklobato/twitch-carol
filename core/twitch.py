"""Twitch OAuth and Helix client shared by api and workers.

Every call has a timeout. Access/refresh tokens are never logged; errors carry
HTTP status only. Pass an httpx.Client to reuse connections or inject a mock
transport in tests; without one, a short-lived client is created per call.
"""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from core.config import get_settings

APP_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_URL = "https://api.twitch.tv/helix"

REQUEST_TIMEOUT_SECONDS = 10.0

# Read-only scopes covering everything the v1 EventSub capture needs.
# Requested up front so streamers consent once; adding scopes later only
# requires extending this list and re-running /auth/login.
OAUTH_SCOPES = [
    "bits:read",
    "channel:read:ads",
    "channel:read:hype_train",
    "channel:read:polls",
    "channel:read:predictions",
    "channel:read:redemptions",
    "channel:read:subscriptions",
    "moderator:read:followers",
]


class TwitchAuthError(Exception):
    pass


class TokenGrant(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    scope: list[str] = []


class TwitchUser(BaseModel):
    id: str
    login: str
    display_name: str


class StreamInfo(BaseModel):
    viewer_count: int
    title: str
    game_name: str
    started_at: datetime


def redirect_uri() -> str:
    return f"{get_settings().public_base_url}/auth/callback"


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": get_settings().twitch_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _http(client: httpx.Client | None):
    if client is not None:
        return nullcontext(client)
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def _post_token(
    grant_fields: dict[str, str], client: httpx.Client | None
) -> TokenGrant:
    settings = get_settings()
    payload = {
        "client_id": settings.twitch_client_id,
        "client_secret": settings.twitch_client_secret,
        **grant_fields,
    }
    with _http(client) as http:
        response = http.post(TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise TwitchAuthError(f"Twitch token endpoint returned {response.status_code}")
    return TokenGrant.model_validate(response.json())


def exchange_code(code: str, client: httpx.Client | None = None) -> TokenGrant:
    return _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
        },
        client,
    )


def refresh_grant(refresh_token: str, client: httpx.Client | None = None) -> TokenGrant:
    return _post_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        client,
    )


def get_user(access_token: str, client: httpx.Client | None = None) -> TwitchUser:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": get_settings().twitch_client_id,
    }
    with _http(client) as http:
        response = http.get(f"{HELIX_URL}/users", headers=headers)
    if response.status_code != 200:
        raise TwitchAuthError(f"Twitch /users returned {response.status_code}")
    data = response.json().get("data", [])
    if not data:
        raise TwitchAuthError("Twitch /users returned no user for the token")
    return TwitchUser.model_validate(data[0])


class _AppTokenCache:
    """Process-local cache for the client_credentials app token."""

    def __init__(self) -> None:
        self.token = ""
        self.expires_at = datetime.min.replace(tzinfo=UTC)

    def valid(self) -> bool:
        return bool(
            self.token
        ) and self.expires_at - APP_TOKEN_REFRESH_MARGIN > datetime.now(UTC)


_app_token = _AppTokenCache()


def get_app_token(client: httpx.Client | None = None) -> str:
    if _app_token.valid():
        return _app_token.token
    settings = get_settings()
    payload = {
        "client_id": settings.twitch_client_id,
        "client_secret": settings.twitch_client_secret,
        "grant_type": "client_credentials",
    }
    with _http(client) as http:
        response = http.post(TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise TwitchAuthError(
            f"Twitch app token endpoint returned {response.status_code}"
        )
    body = response.json()
    _app_token.token = body["access_token"]
    _app_token.expires_at = datetime.now(UTC) + timedelta(seconds=body["expires_in"])
    return _app_token.token


def app_headers(client: httpx.Client | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_app_token(client)}",
        "Client-Id": get_settings().twitch_client_id,
    }


def get_stream_info(
    broadcaster_id: int, client: httpx.Client | None = None
) -> StreamInfo | None:
    """Helix Get Streams: returns None when the channel is offline."""
    with _http(client) as http:
        response = http.get(
            f"{HELIX_URL}/streams",
            params={"user_id": str(broadcaster_id)},
            headers=app_headers(client),
        )
    if response.status_code != 200:
        raise TwitchAuthError(f"Twitch /streams returned {response.status_code}")
    data = response.json().get("data", [])
    if not data:
        return None
    return StreamInfo.model_validate(data[0])
