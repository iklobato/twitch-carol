"""StreamElements tips connector: pulls a channel's tips (donations) so external
revenue lands in the consolidated finance view. Twitch's API never exposes tips,
so this is where a big slice of a streamer's income comes from.

Auth is the channel's StreamElements JWT (dashboard -> account -> show secrets).
"""

from datetime import datetime

import httpx
from pydantic import BaseModel

API_BASE = "https://api.streamelements.com/kappa/v2"
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
