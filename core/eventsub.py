"""EventSub webhook plumbing: HMAC signature, dedup, subscription sync.

Twitch signs each webhook message with HMAC-SHA256 over
message_id + timestamp + raw_body using the shared TWITCH_EVENTSUB_SECRET.
"""

import hashlib
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import redis

from core.config import get_settings
from core.models import Channel
from core.twitch import HELIX_URL, app_headers

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


def claim_message(valkey: redis.Redis, message_id: str) -> bool:
    """Returns False when this message id was already processed (Twitch retries)."""
    return bool(
        valkey.set(f"eventsub:msg:{message_id}", 1, nx=True, ex=DEDUP_TTL_SECONDS)
    )


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
    own_client = client if client is not None else httpx.Client(timeout=10.0)

    existing = _existing_subscription_types(own_client, broadcaster_id)
    summary: dict[str, list[str]] = {
        "created": [],
        "existing": [],
        "skipped": [],
        "failed": [],
    }

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
        response = own_client.post(
            f"{HELIX_URL}/eventsub/subscriptions",
            headers=app_headers(own_client),
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

    if client is None:
        own_client.close()
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
