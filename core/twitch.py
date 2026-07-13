"""Twitch OAuth and Helix client shared by api and workers.

Every call has a timeout. Access/refresh tokens are never logged; errors carry
HTTP status only. Pass an httpx.Client to reuse connections or inject a mock
transport in tests; without one, a short-lived client is created per call.
"""

import logging
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from core.config import get_settings

logger = logging.getLogger(__name__)

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
    "channel:read:goals",
    "channel:read:hype_train",
    "channel:read:polls",
    "channel:read:predictions",
    "channel:read:redemptions",
    "channel:read:subscriptions",
    "channel:read:vips",
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


class FollowerRecord(BaseModel):
    user_id: str
    user_login: str
    followed_at: datetime


class VideoRecord(BaseModel):
    id: str
    title: str
    created_at: datetime
    duration_seconds: int
    view_count: int
    url: str


def _user_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": get_settings().twitch_client_id,
    }


HELIX_PAGE_SIZE = 100
# Backstop only: pagination stops at the true end via the cursor. This caps a
# pathological inline backfill; move to a background job before onboarding
# channels with hundreds of thousands of followers.
FOLLOWER_PAGE_CAP = 200
_DURATION_UNITS = {"h": 3600, "m": 60, "s": 1}


def _duration_to_seconds(text: str) -> int:
    """Twitch video durations look like '3h8m33s' / '27m' / '58s'."""
    total = 0
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif char in _DURATION_UNITS and digits:
            total += int(digits) * _DURATION_UNITS[char]
            digits = ""
    return total


def iter_followers(
    broadcaster_id: int, access_token: str, client: httpx.Client | None = None
) -> Iterator[FollowerRecord]:
    """Helix Get Channel Followers, most-recent-first, paginated to the end."""
    cursor: str | None = None
    with _http(client) as http:
        for _ in range(FOLLOWER_PAGE_CAP):
            params = {
                "broadcaster_id": str(broadcaster_id),
                "first": str(HELIX_PAGE_SIZE),
            }
            if cursor:
                params["after"] = cursor
            response = http.get(
                f"{HELIX_URL}/channels/followers",
                params=params,
                headers=_user_headers(access_token),
            )
            if response.status_code != 200:
                raise TwitchAuthError(
                    f"Twitch /channels/followers returned {response.status_code}"
                )
            body = response.json()
            for row in body.get("data", []):
                yield FollowerRecord.model_validate(row)
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor:
                return
        logger.warning(
            "follower backfill hit page cap; not all followers captured",
            extra={"broadcaster_id": broadcaster_id},
        )


def get_videos(
    user_id: int, access_token: str, client: httpx.Client | None = None
) -> list[VideoRecord]:
    """Helix Get Videos (archived broadcasts). One page: Twitch retains VODs for
    14 days (60 for partners), so the most recent 100 covers what exists."""
    with _http(client) as http:
        response = http.get(
            f"{HELIX_URL}/videos",
            params={
                "user_id": str(user_id),
                "type": "archive",
                "first": str(HELIX_PAGE_SIZE),
            },
            headers=_user_headers(access_token),
        )
    if response.status_code != 200:
        raise TwitchAuthError(f"Twitch /videos returned {response.status_code}")
    return [
        VideoRecord(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            duration_seconds=_duration_to_seconds(row["duration"]),
            view_count=int(row["view_count"]),
            url=row["url"],
        )
        for row in response.json().get("data", [])
    ]


class VipRecord(BaseModel):
    user_id: str
    user_login: str


class GoalRecord(BaseModel):
    id: str
    type: str
    description: str | None = None
    current_amount: int
    target_amount: int


def get_vips(
    broadcaster_id: int, access_token: str, client: httpx.Client | None = None
) -> list[VipRecord]:
    """Helix Get VIPs (paginated to the end)."""
    vips: list[VipRecord] = []
    cursor: str | None = None
    with _http(client) as http:
        for _ in range(FOLLOWER_PAGE_CAP):
            params = {
                "broadcaster_id": str(broadcaster_id),
                "first": str(HELIX_PAGE_SIZE),
            }
            if cursor:
                params["after"] = cursor
            response = http.get(
                f"{HELIX_URL}/channels/vips",
                params=params,
                headers=_user_headers(access_token),
            )
            if response.status_code != 200:
                raise TwitchAuthError(
                    f"Twitch /channels/vips returned {response.status_code}"
                )
            body = response.json()
            vips.extend(VipRecord.model_validate(row) for row in body.get("data", []))
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor:
                break
    return vips


def get_goals(
    broadcaster_id: int, access_token: str, client: httpx.Client | None = None
) -> list[GoalRecord]:
    """Helix Get Creator Goals (current goals snapshot)."""
    with _http(client) as http:
        response = http.get(
            f"{HELIX_URL}/goals",
            params={"broadcaster_id": str(broadcaster_id)},
            headers=_user_headers(access_token),
        )
    if response.status_code != 200:
        raise TwitchAuthError(f"Twitch /goals returned {response.status_code}")
    return [GoalRecord.model_validate(row) for row in response.json().get("data", [])]


class SubscriptionRecord(BaseModel):
    user_id: str
    user_login: str
    tier: str
    is_gift: bool = False
    gifter_login: str | None = None


class BitsLeaderRecord(BaseModel):
    user_login: str
    rank: int
    score: int


def get_subscriptions(
    broadcaster_id: int, access_token: str, client: httpx.Client | None = None
) -> list[SubscriptionRecord]:
    """Helix Get Broadcaster Subscriptions (affiliate/partner only; returns an
    empty list for a channel that has not monetized)."""
    subs: list[SubscriptionRecord] = []
    cursor: str | None = None
    with _http(client) as http:
        for _ in range(FOLLOWER_PAGE_CAP):
            params = {
                "broadcaster_id": str(broadcaster_id),
                "first": str(HELIX_PAGE_SIZE),
            }
            if cursor:
                params["after"] = cursor
            response = http.get(
                f"{HELIX_URL}/subscriptions",
                params=params,
                headers=_user_headers(access_token),
            )
            if response.status_code != 200:
                raise TwitchAuthError(
                    f"Twitch /subscriptions returned {response.status_code}"
                )
            body = response.json()
            subs.extend(
                SubscriptionRecord.model_validate(row) for row in body.get("data", [])
            )
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor:
                break
    return subs


def get_bits_leaderboard(
    access_token: str, client: httpx.Client | None = None
) -> list[BitsLeaderRecord]:
    """Helix Get Bits Leaderboard, all-time (affiliate only; empty otherwise).
    The broadcaster is implied by the user token, so no broadcaster_id."""
    with _http(client) as http:
        response = http.get(
            f"{HELIX_URL}/bits/leaderboard",
            params={"count": str(HELIX_PAGE_SIZE), "period": "all"},
            headers=_user_headers(access_token),
        )
    if response.status_code != 200:
        raise TwitchAuthError(
            f"Twitch /bits/leaderboard returned {response.status_code}"
        )
    return [
        BitsLeaderRecord.model_validate(row) for row in response.json().get("data", [])
    ]


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
