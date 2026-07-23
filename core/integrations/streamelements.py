"""StreamElements tips connector: pulls a channel's tips (donations) so external
revenue lands in the consolidated finance view. Twitch's API never exposes tips,
so this is where a big slice of a streamer's income comes from.

Auth is the channel's StreamElements JWT (dashboard -> account -> show secrets).
"""

from datetime import datetime

import httpx
from pydantic import BaseModel

from core.config import get_settings

API_BASE = "https://api.streamelements.com/kappa/v2"
OAUTH_AUTHORIZE = "https://api.streamelements.com/oauth2/authorize"
OAUTH_TOKEN = "https://api.streamelements.com/oauth2/token"
# activities:read lets the token read the full activity feed (merch, redemptions),
# so extra revenue sources can be ingested later without another re-connect.
SE_SCOPES = ("tips:read", "activities:read", "channel:read")
CALLBACK_PATH = "/api/integrations/streamelements/callback"
TIMEOUT_SECONDS = 20.0
PAGE_LIMIT = 100
MAX_PAGES = 20  # safety cap: PAGE_LIMIT * MAX_PAGES tips per sync


class StreamElementsError(Exception):
    pass


class RemoteTip(BaseModel):
    external_id: str
    amount: float
    currency: str
    tipper: str | None
    message: str | None
    tipped_at: datetime


def _parse(doc: dict) -> RemoteTip | None:
    donation = doc.get("donation") or {}
    amount = donation.get("amount")
    created = doc.get("createdAt")
    if amount is None or created is None or not doc.get("_id"):
        return None
    user = donation.get("user") or {}
    return RemoteTip(
        external_id=str(doc["_id"]),
        amount=float(amount),
        currency=str(donation.get("currency") or "USD"),
        tipper=user.get("username"),
        message=donation.get("message"),
        tipped_at=datetime.fromisoformat(created.replace("Z", "+00:00")),
    )


def fetch_tips(
    account_id: str,
    jwt: str,
    after: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[RemoteTip]:
    """Every tip since `after` (or all, capped), oldest first. Paginates by
    offset until a short page or the cap."""
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    headers = {"Authorization": f"Bearer {jwt}"}
    tips: list[RemoteTip] = []
    for page in range(MAX_PAGES):
        params: dict[str, str | int] = {
            "limit": PAGE_LIMIT,
            "offset": page * PAGE_LIMIT,
            "sort": "createdAt",
        }
        if after is not None:
            params["after"] = after.isoformat()
        response = http.get(
            f"{API_BASE}/tips/{account_id}", headers=headers, params=params
        )
        if response.status_code != 200:
            raise StreamElementsError(
                f"StreamElements tips returned {response.status_code}"
            )
        docs = response.json().get("docs", [])
        tips.extend(tip for tip in (_parse(doc) for doc in docs) if tip is not None)
        if len(docs) < PAGE_LIMIT:
            break
    tips.sort(key=lambda t: t.tipped_at)
    return tips


class SEToken(BaseModel):
    access_token: str
    refresh_token: str | None
    expires_in: int  # seconds until the access token expires


def _redirect_uri() -> str:
    return get_settings().public_base_url + CALLBACK_PATH


def build_authorize_url(state: str) -> str:
    settings = get_settings()
    params = httpx.QueryParams(
        {
            "client_id": settings.streamelements_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": " ".join(SE_SCOPES),
            "state": state,
        }
    )
    return f"{OAUTH_AUTHORIZE}?{params}"


def _post_token(data: dict[str, str], client: httpx.Client | None = None) -> SEToken:
    settings = get_settings()
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    response = http.post(
        OAUTH_TOKEN,
        data={
            **data,
            "client_id": settings.streamelements_client_id,
            "client_secret": settings.streamelements_client_secret,
        },
    )
    if response.status_code != 200:
        raise StreamElementsError(f"OAuth token returned {response.status_code}")
    body = response.json()
    return SEToken(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_in=int(body.get("expires_in", 0)),
    )


def exchange_code(code: str, client: httpx.Client | None = None) -> SEToken:
    return _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
        client=client,
    )


def refresh_access_token(
    refresh_token: str, client: httpx.Client | None = None
) -> SEToken:
    return _post_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}, client=client
    )


def fetch_channel_id(access_token: str, client: httpx.Client | None = None) -> str:
    """The StreamElements channel `_id` for the authorized user; this is the
    account id every kappa/v2 data endpoint is keyed by."""
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    response = http.get(
        f"{API_BASE}/channels/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code != 200:
        raise StreamElementsError(f"channels/me returned {response.status_code}")
    channel_id = response.json().get("_id")
    if not channel_id:
        raise StreamElementsError("channels/me missing _id")
    return str(channel_id)
