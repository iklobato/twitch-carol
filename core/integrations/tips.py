"""External tips ingestion: store a channel's off-Twitch donations (dedup by
source + external id) so finance can consolidate total revenue. DB-touching
service kept apart from the pure StreamElements client."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.crypto import decrypt_secret, encrypt_secret
from core.integrations.streamelements import SEToken, fetch_tips, refresh_access_token
from core.models import Channel, ExternalTip

SOURCE_STREAMELEMENTS = "streamelements"
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


def sync_streamelements_tips(db: Session, channel: Channel) -> int:
    """Pull tips since the last sync and store the new ones. Returns how many
    were added. No-op (0) when the channel hasn't connected StreamElements."""
    token = _valid_access_token(db, channel)
    if token is None and channel.streamelements_jwt_encrypted is not None:
        token = decrypt_secret(channel.streamelements_jwt_encrypted)
    if not channel.streamelements_account_id or token is None:
        return 0
    tips = fetch_tips(
        channel.streamelements_account_id, token, after=channel.streamelements_synced_at
    )
    seen = set(
        db.scalars(
            select(ExternalTip.external_id).where(
                ExternalTip.channel_id == channel.id,
                ExternalTip.source == SOURCE_STREAMELEMENTS,
            )
        )
    )
    added = 0
    for tip in tips:
        if tip.external_id in seen:
            continue
        db.add(
            ExternalTip(
                channel_id=channel.id,
                source=SOURCE_STREAMELEMENTS,
                external_id=tip.external_id,
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
