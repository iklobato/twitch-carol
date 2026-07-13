"""Monetary interpretation of captured channel events. Values are ESTIMATES
of the streamer's take, since Twitch's exact split is private; the UI labels
them as estimates. Populates only once a channel monetizes (bits/subs), which
requires Twitch affiliate status."""

from core.models import Event

BITS_USD = 0.01  # streamer receives ~US$0.01 per bit
SUB_TIER_USD = {1000: 2.5, 2000: 5.0, 3000: 12.5}  # ~50% of 4.99/9.99/24.99
DEFAULT_TIER = 1000

CHEER = "channel.cheer"
SUBSCRIBE = "channel.subscribe"
RESUB = "channel.subscription.message"
GIFT = "channel.subscription.gift"
MONEY_EVENT_TYPES = frozenset({CHEER, SUBSCRIBE, RESUB, GIFT})


def _tier(event: Event) -> int:
    tier = (event.payload or {}).get("tier")
    try:
        return int(tier) if tier is not None else DEFAULT_TIER
    except (TypeError, ValueError):
        return DEFAULT_TIER


def event_usd(event: Event) -> float:
    """Estimated USD value to the streamer for one money event."""
    if event.type == CHEER:
        return round((event.amount or 0) * BITS_USD, 2)
    if event.type in (SUBSCRIBE, RESUB):
        # amount holds the tier for subs
        return SUB_TIER_USD.get(
            event.amount or DEFAULT_TIER, SUB_TIER_USD[DEFAULT_TIER]
        )
    if event.type == GIFT:
        # amount holds how many subs were gifted; tier is in the payload
        return round(
            (event.amount or 0)
            * SUB_TIER_USD.get(_tier(event), SUB_TIER_USD[DEFAULT_TIER]),
            2,
        )
    return 0.0


def event_contributor(event: Event) -> str | None:
    payload = event.payload or {}
    login = payload.get("user_login") or payload.get("user_name")
    return str(login) if login else None
