"""One-time backfill on channel connect. Twitch serves follower history (with
followed_at) and past VODs (with created_at) over REST, so a freshly connected
account shows real data before any live capture. Everything else (chat,
viewers, money, engagement) is forward-only and cannot be backfilled."""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.channels import ensure_fresh_token
from core.models import Channel, Follower, PastBroadcast
from core.twitch import get_videos, iter_followers

logger = logging.getLogger(__name__)


def backfill_followers(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Seed the followers table from Helix. Returns how many new rows were added
    (already-known followers are skipped, so re-connecting is cheap)."""
    token = ensure_fresh_token(db, channel, client)
    known = set(
        db.scalars(
            select(Follower.twitch_user_id).where(Follower.channel_id == channel.id)
        )
    )
    added = 0
    for record in iter_followers(channel.twitch_user_id, token, client):
        user_id = int(record.user_id)
        if user_id in known:
            continue
        known.add(user_id)
        db.add(
            Follower(
                channel_id=channel.id,
                twitch_user_id=user_id,
                login=record.user_login,
                followed_at=record.followed_at,
            )
        )
        added += 1
    return added


def backfill_videos(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Seed past broadcasts from Helix VODs. Returns how many new rows were
    added; view counts on already-stored VODs are refreshed in place."""
    token = ensure_fresh_token(db, channel, client)
    stored = {
        row.twitch_video_id: row
        for row in db.scalars(
            select(PastBroadcast).where(PastBroadcast.channel_id == channel.id)
        )
    }
    added = 0
    for video in get_videos(channel.twitch_user_id, token, client):
        existing = stored.get(video.id)
        if existing is not None:
            existing.view_count = video.view_count
            continue
        db.add(
            PastBroadcast(
                channel_id=channel.id,
                twitch_video_id=video.id,
                title=video.title,
                published_at=video.created_at,
                duration_seconds=video.duration_seconds,
                view_count=video.view_count,
                url=video.url,
            )
        )
        added += 1
    return added
