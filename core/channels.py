"""Channel persistence: OAuth token storage (encrypted) and refresh."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.crypto import decrypt_secret, encrypt_secret
from core.models import Channel
from core.twitch import TokenGrant, TwitchAuthError, TwitchUser, refresh_grant

TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


def upsert_channel(db: Session, user: TwitchUser, grant: TokenGrant) -> Channel:
    channel = db.scalar(select(Channel).where(Channel.twitch_user_id == int(user.id)))
    if channel is None:
        channel = Channel(
            twitch_user_id=int(user.id),
            login=user.login,
            display_name=user.display_name,
        )
        db.add(channel)
    channel.login = user.login
    channel.display_name = user.display_name
    _store_grant(channel, grant)
    db.flush()
    return channel


def ensure_fresh_token(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> str:
    """Returns a valid access token, refreshing (and persisting the rotated
    refresh token) when close to expiry."""
    if _token_still_valid(channel) and channel.access_token_encrypted is not None:
        return decrypt_secret(channel.access_token_encrypted)
    if channel.refresh_token_encrypted is None:
        raise TwitchAuthError(f"Channel {channel.login} has no refresh token stored")
    grant = refresh_grant(decrypt_secret(channel.refresh_token_encrypted), client)
    _store_grant(channel, grant)
    db.flush()
    return grant.access_token


def _token_still_valid(channel: Channel) -> bool:
    if channel.token_expires_at is None:
        return False
    return channel.token_expires_at - TOKEN_REFRESH_MARGIN > datetime.now(UTC)


def _store_grant(channel: Channel, grant: TokenGrant) -> None:
    channel.access_token_encrypted = encrypt_secret(grant.access_token)
    channel.refresh_token_encrypted = encrypt_secret(grant.refresh_token)
    channel.scopes = grant.scope
    channel.token_expires_at = datetime.now(UTC) + timedelta(seconds=grant.expires_in)
