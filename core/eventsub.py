"""EventSub webhook plumbing: HMAC signature, dedup, subscription sync.

Twitch signs each webhook message with HMAC-SHA256 over
message_id + timestamp + raw_body using the shared TWITCH_EVENTSUB_SECRET.
"""

import hashlib
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Channel, EventSubMessage
from core.twitch import HELIX_URL, _http, app_headers

logger = logging.getLogger(__name__)

SIGNATURE_PREFIX = "sha256="
HEADER_MESSAGE_ID = "Twitch-Eventsub-Message-Id"
HEADER_TIMESTAMP = "Twitch-Eventsub-Message-Timestamp"
HEADER_SIGNATURE = "Twitch-Eventsub-Message-Signature"
HEADER_MESSAGE_TYPE = "Twitch-Eventsub-Message-Type"

MESSAGE_TYPE_VERIFICATION = "webhook_callback_verification"
MESSAGE_TYPE_NOTIFICATION = "notification"
MESSAGE_TYPE_REVOCATION = "revocation"

MESSAGE_MAX_AGE_SECONDS = 600
DEDUP_TTL_SECONDS = 600


def compute_signature(secret: str, message_id: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(
        secret.encode(), message_id.encode() + timestamp.encode() + body, hashlib.sha256
    )
    return SIGNATURE_PREFIX + digest.hexdigest()


def verify_signature(
    secret: str, message_id: str, timestamp: str, signature: str, body: bytes
) -> bool:
    expected = compute_signature(secret, message_id, timestamp, body)
    return hmac.compare_digest(expected, signature)


def timestamp_is_fresh(timestamp: str, now: datetime | None = None) -> bool:
    try:
        sent_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    reference = now if now is not None else datetime.now(UTC)
    return abs((reference - sent_at).total_seconds()) <= MESSAGE_MAX_AGE_SECONDS


def claim_message(db: Session, message_id: str) -> bool:
    """Returns False when this message id was already processed (Twitch retries).

    Postgres, not Valkey: this dedup was the app's only real use of Valkey in
    production, and the cluster sits in another region. Private networking is
    regional, so keeping it meant talking to a managed service over a public
    host. The primary key makes the claim atomic exactly like SET NX did.

    Committed immediately: a concurrent retry has to see the claim, which is the
    whole point. Rows past the retry window are pruned here, so the table is a
    fixed-size window and never a log that grows forever.
    """
    db.execute(
        delete(EventSubMessage).where(
            EventSubMessage.received_at
            < datetime.now(UTC) - timedelta(seconds=DEDUP_TTL_SECONDS)
        )
    )
    # ON CONFLICT DO NOTHING returns no row when the id was already claimed.
    claimed = db.execute(
        pg_insert(EventSubMessage)
        .values(message_id=message_id)
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(EventSubMessage.message_id)
    ).scalar_one_or_none()
    db.commit()
    return claimed is not None


def _broadcaster_condition(broadcaster_id: str) -> dict[str, str]:
    return {"broadcaster_user_id": broadcaster_id}


def _follow_condition(broadcaster_id: str) -> dict[str, str]:
    return {"broadcaster_user_id": broadcaster_id, "moderator_user_id": broadcaster_id}


def _raid_condition(broadcaster_id: str) -> dict[str, str]:
    return {"to_broadcaster_user_id": broadcaster_id}


@dataclass(frozen=True)
class SubscriptionSpec:
    type: str
    version: str
    required_scope: str | None
    condition: Callable[[str], dict[str, str]] = _broadcaster_condition


# hype_train uses v2: the v1 subscription types are deprecated (Helix returned
# 410 for the legacy endpoint during M2 validation).
SUBSCRIPTION_SPECS = [
    SubscriptionSpec("stream.online", "1", None),
    SubscriptionSpec("stream.offline", "1", None),
    SubscriptionSpec("channel.update", "2", None),
    SubscriptionSpec("channel.raid", "1", None, _raid_condition),
    SubscriptionSpec(
        "channel.follow", "2", "moderator:read:followers", _follow_condition
    ),
    SubscriptionSpec("channel.subscribe", "1", "channel:read:subscriptions"),
    SubscriptionSpec("channel.subscription.end", "1", "channel:read:subscriptions"),
    SubscriptionSpec("channel.subscription.gift", "1", "channel:read:subscriptions"),
    SubscriptionSpec("channel.subscription.message", "1", "channel:read:subscriptions"),
    SubscriptionSpec("channel.cheer", "1", "bits:read"),
    SubscriptionSpec(
        "channel.channel_points_custom_reward_redemption.add",
        "1",
        "channel:read:redemptions",
    ),
    SubscriptionSpec("channel.hype_train.begin", "2", "channel:read:hype_train"),
    SubscriptionSpec("channel.hype_train.progress", "2", "channel:read:hype_train"),
    SubscriptionSpec("channel.hype_train.end", "2", "channel:read:hype_train"),
    SubscriptionSpec("channel.poll.begin", "1", "channel:read:polls"),
    SubscriptionSpec("channel.poll.end", "1", "channel:read:polls"),
    SubscriptionSpec("channel.prediction.begin", "1", "channel:read:predictions"),
    SubscriptionSpec("channel.prediction.end", "1", "channel:read:predictions"),
    SubscriptionSpec("channel.ad_break.begin", "1", "channel:read:ads"),
]


def specs_allowed_by_scopes(scopes: list[str]) -> list[SubscriptionSpec]:
    return [
        s
        for s in SUBSCRIPTION_SPECS
        if s.required_scope is None or s.required_scope in scopes
    ]


def sync_channel_subscriptions(
    channel: Channel, client: httpx.Client | None = None
) -> dict[str, list[str]]:
    """Creates missing EventSub webhook subscriptions for a channel.

    Only subscribes to types the granted scopes allow; per-type failures
    (e.g. affiliate-only) are recorded, not raised. Requires an HTTPS
    PUBLIC_BASE_URL, as Twitch rejects plain-http callbacks.
    """
    settings = get_settings()
    callback = f"{settings.public_base_url}/eventsub/callback"
    broadcaster_id = str(channel.twitch_user_id)
    summary: dict[str, list[str]] = {
        "created": [],
        "existing": [],
        "skipped": [],
        "failed": [],
    }

    # _http is the single Twitch-client seam (tests swap it for a fake)
    with _http(client) as http:
        existing = _existing_subscription_types(http, broadcaster_id)
        for spec in SUBSCRIPTION_SPECS:
            if (
                spec.required_scope is not None
                and spec.required_scope not in channel.scopes
            ):
                summary["skipped"].append(spec.type)
                continue
            if spec.type in existing:
                summary["existing"].append(spec.type)
                continue
            response = http.post(
                f"{HELIX_URL}/eventsub/subscriptions",
                headers=app_headers(http),
                json={
                    "type": spec.type,
                    "version": spec.version,
                    "condition": spec.condition(broadcaster_id),
                    "transport": {
                        "method": "webhook",
                        "callback": callback,
                        "secret": settings.twitch_eventsub_secret,
                    },
                },
            )
            if response.status_code == 202:
                summary["created"].append(spec.type)
                continue
            summary["failed"].append(f"{spec.type}:{response.status_code}")
            logger.warning(
                "eventsub subscription failed",
                extra={"channel_id": channel.id, "event_type": spec.type},
            )
    return summary


def _existing_subscription_types(client: httpx.Client, broadcaster_id: str) -> set[str]:
    response = client.get(
        f"{HELIX_URL}/eventsub/subscriptions",
        params={"user_id": broadcaster_id},
        headers=app_headers(client),
    )
    if response.status_code != 200:
        return set()
    active = {"enabled", "webhook_callback_verification_pending"}
    return {
        sub["type"]
        for sub in response.json().get("data", [])
        if sub.get("status") in active
    }
