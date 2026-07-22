"""External tips ingestion: store a channel's off-Twitch donations (dedup by
source + external id) so finance can consolidate total revenue. DB-touching
service kept apart from the pure StreamElements client."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.crypto import decrypt_secret, encrypt_secret
from core.integrations.streamelements import fetch_tips
from core.models import Channel, ExternalTip

SOURCE_STREAMELEMENTS = "streamelements"


def set_streamelements_credentials(
    db: Session, channel: Channel, account_id: str, jwt: str
) -> None:
    channel.streamelements_account_id = account_id
    channel.streamelements_jwt_encrypted = encrypt_secret(jwt)
    db.commit()


def sync_streamelements_tips(db: Session, channel: Channel) -> int:
    """Pull tips since the last sync and store the new ones. Returns how many
    were added. No-op (0) when the channel hasn't connected StreamElements."""
    if (
        not channel.streamelements_account_id
        or channel.streamelements_jwt_encrypted is None
    ):
        return 0
    jwt = decrypt_secret(channel.streamelements_jwt_encrypted)
    tips = fetch_tips(
        channel.streamelements_account_id, jwt, after=channel.streamelements_synced_at
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
