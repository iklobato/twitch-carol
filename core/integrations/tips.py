"""External tips ingestion: store a channel's off-Twitch donations (dedup by
source + external id) so finance can consolidate total revenue. DB-touching
service kept apart from the pure StreamElements client."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.crypto import decrypt_secret, encrypt_secret
from core.integrations.streamelements import (
    SEToken,
    fetch_loyalty_top,
    fetch_merch,
    fetch_tips,
    refresh_access_token,
)
from core.models import Channel, ExternalTip, LoyaltyEntry

SOURCE_STREAMELEMENTS = "streamelements"
KIND_TIP = "tip"
KIND_MERCH = "merch"
# Refresh a little before the token actually expires to avoid racing expiry.
TOKEN_REFRESH_SKEW = timedelta(seconds=60)


def set_streamelements_credentials(
    db: Session, channel: Channel, account_id: str, jwt: str
) -> None:
    channel.streamelements_account_id = account_id
    channel.streamelements_jwt_encrypted = encrypt_secret(jwt)
    db.commit()


def set_streamelements_oauth(
    db: Session, channel: Channel, account_id: str, token: SEToken
) -> None:
    """Store the OAuth tokens from the Connect flow. Keeps an existing refresh
    token when a refresh-grant response omits a new one."""
    channel.streamelements_account_id = account_id
    channel.streamelements_token_encrypted = encrypt_secret(token.access_token)
    if token.refresh_token:
        channel.streamelements_refresh_encrypted = encrypt_secret(token.refresh_token)
    channel.streamelements_token_expires_at = datetime.now(UTC) + timedelta(
        seconds=token.expires_in
    )
    db.commit()


def _valid_access_token(db: Session, channel: Channel) -> str | None:
    """Decrypted OAuth access token, refreshed if expired. None when the channel
    connected via the legacy JWT (or not at all)."""
    if channel.streamelements_token_encrypted is None:
        return None
    expires_at = channel.streamelements_token_expires_at
    is_fresh = expires_at is None or datetime.now(UTC) < expires_at - TOKEN_REFRESH_SKEW
    if is_fresh or channel.streamelements_refresh_encrypted is None:
        return decrypt_secret(channel.streamelements_token_encrypted)
    token = refresh_access_token(
        decrypt_secret(channel.streamelements_refresh_encrypted)
    )
    set_streamelements_oauth(
        db, channel, channel.streamelements_account_id or "", token
    )
    return token.access_token


def _resolve_token(db: Session, channel: Channel) -> str | None:
    """The Bearer token for StreamElements calls: the OAuth access token
    (refreshed if needed), else the legacy JWT, else None (not connected)."""
    token = _valid_access_token(db, channel)
    if token is None and channel.streamelements_jwt_encrypted is not None:
        token = decrypt_secret(channel.streamelements_jwt_encrypted)
    return token


def _stored_external_ids(db: Session, channel_id: int) -> set[str]:
    return set(
        db.scalars(
            select(ExternalTip.external_id).where(
                ExternalTip.channel_id == channel_id,
                ExternalTip.source == SOURCE_STREAMELEMENTS,
            )
        )
    )


def sync_streamelements_tips(db: Session, channel: Channel) -> int:
    """Pull tips since the last sync and store the new ones. Returns how many
    were added. No-op (0) when the channel hasn't connected StreamElements."""
    token = _resolve_token(db, channel)
    if not channel.streamelements_account_id or token is None:
        return 0
    tips = fetch_tips(
        channel.streamelements_account_id, token, after=channel.streamelements_synced_at
    )
    seen = _stored_external_ids(db, channel.id)
    added = 0
    for tip in tips:
        if tip.external_id in seen:
            continue
        db.add(
            ExternalTip(
                channel_id=channel.id,
                source=SOURCE_STREAMELEMENTS,
                external_id=tip.external_id,
                kind=KIND_TIP,
                amount=tip.amount,
                currency=tip.currency,
                tipper=tip.tipper,
                message=tip.message,
                tipped_at=tip.tipped_at,
            )
        )
        added += 1
    channel.streamelements_synced_at = datetime.now(UTC)
    db.commit()
    return added


def sync_streamelements_merch(
    db: Session, channel: Channel, after: datetime | None = None
) -> int:
    """Pull merch/store sales and store the new ones as merch-kind rows (dedup by
    external id). Returns how many were added. `after` is a fetch optimization;
    dedup guarantees correctness regardless."""
    token = _resolve_token(db, channel)
    if not channel.streamelements_account_id or token is None:
        return 0
    sales = fetch_merch(channel.streamelements_account_id, token, after=after)
    seen = _stored_external_ids(db, channel.id)
    added = 0
    for sale in sales:
        if sale.external_id in seen:
            continue
        db.add(
            ExternalTip(
                channel_id=channel.id,
                source=SOURCE_STREAMELEMENTS,
                external_id=sale.external_id,
                kind=KIND_MERCH,
                amount=sale.amount,
                currency=sale.currency,
                tipper=sale.actor,
                message=None,
                tipped_at=sale.occurred_at,
            )
        )
        added += 1
    db.commit()
    return added


def sync_streamelements_loyalty(db: Session, channel: Channel) -> int:
    """Replace the channel's loyalty leaderboard snapshot. Returns the number of
    ranked entries stored."""
    token = _resolve_token(db, channel)
    if not channel.streamelements_account_id or token is None:
        return 0
    entries = fetch_loyalty_top(channel.streamelements_account_id, token)
    db.execute(delete(LoyaltyEntry).where(LoyaltyEntry.channel_id == channel.id))
    now = datetime.now(UTC)
    for rank, entry in enumerate(entries, start=1):
        db.add(
            LoyaltyEntry(
                channel_id=channel.id,
                username=entry.username,
                points=entry.points,
                rank=rank,
                synced_at=now,
            )
        )
    db.commit()
    return len(entries)


def sync_streamelements(db: Session, channel: Channel) -> dict[str, int]:
    """Pull everything StreamElements gives that Twitch doesn't: tips, merch, and
    the loyalty leaderboard. Merch/loyalty use the pre-tips cursor so tips
    advancing `synced_at` can't make them skip a window."""
    since = channel.streamelements_synced_at
    tips = sync_streamelements_tips(db, channel)
    merch = sync_streamelements_merch(db, channel, after=since)
    loyalty = sync_streamelements_loyalty(db, channel)
    return {"tips": tips, "merch": merch, "loyalty": loyalty}
