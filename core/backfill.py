"""One-time backfill on channel connect. Twitch serves follower history (with
followed_at) and past VODs (with created_at) over REST, so a freshly connected
account shows real data before any live capture. Everything else (chat,
viewers, money, engagement) is forward-only and cannot be backfilled."""

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.channels import ensure_fresh_token
from core.models import (
    BitsLeader,
    Channel,
    Follower,
    Goal,
    PastBroadcast,
    Subscription,
    Vip,
)
from core.twitch import (
    get_bits_leaderboard,
    get_goals,
    get_subscriptions,
    get_users_by_ids,
    get_videos,
    get_vips,
    iter_followers,
)

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


ENRICH_BATCH_SIZE = 100


def enrich_followers(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Fill profile fields (name, avatar, bio, broadcaster_type, account age)
    for followers not yet enriched, via Helix Get Users. Resumable: only rows
    with enriched_at IS NULL are fetched, so a partial run picks up where it
    stopped. Returns how many followers were enriched."""
    pending = list(
        db.scalars(
            select(Follower)
            .where(Follower.channel_id == channel.id)
            .where(Follower.enriched_at.is_(None))
        )
    )
    if not pending:
        return 0
    by_id = {follower.twitch_user_id: follower for follower in pending}
    now = datetime.now(UTC)
    enriched = 0
    for start in range(0, len(pending), ENRICH_BATCH_SIZE):
        batch = pending[start : start + ENRICH_BATCH_SIZE]
        profiles = get_users_by_ids([f.twitch_user_id for f in batch], client)
        for profile in profiles:
            follower = by_id.get(int(profile.id))
            if follower is None:
                continue
            follower.login = profile.login
            follower.display_name = profile.display_name
            follower.profile_image_url = profile.profile_image_url
            follower.description = profile.description
            follower.broadcaster_type = profile.broadcaster_type
            follower.account_created_at = profile.created_at
            follower.enriched_at = now
            enriched += 1
        # Stamp the rest of the batch too: an id Twitch dropped (banned/deleted)
        # must not be retried forever.
        for follower in batch:
            if follower.enriched_at is None:
                follower.enriched_at = now
    return enriched


def backfill_vips(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Seed the channel's VIPs from Helix. Returns how many new rows were added."""
    token = ensure_fresh_token(db, channel, client)
    known = set(
        db.scalars(select(Vip.twitch_user_id).where(Vip.channel_id == channel.id))
    )
    added = 0
    for record in get_vips(channel.twitch_user_id, token, client):
        user_id = int(record.user_id)
        if user_id in known:
            continue
        known.add(user_id)
        db.add(
            Vip(
                channel_id=channel.id,
                twitch_user_id=user_id,
                login=record.user_login,
            )
        )
        added += 1
    return added


def backfill_goals(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Replace the channel's goal snapshot with the current Helix state. Goals
    are point-in-time, so the whole set is refreshed on each connect."""
    token = ensure_fresh_token(db, channel, client)
    stored = {
        row.twitch_goal_id: row
        for row in db.scalars(select(Goal).where(Goal.channel_id == channel.id))
    }
    seen: set[str] = set()
    added = 0
    for goal in get_goals(channel.twitch_user_id, token, client):
        seen.add(goal.id)
        existing = stored.get(goal.id)
        if existing is not None:
            existing.current_amount = goal.current_amount
            existing.target_amount = goal.target_amount
            existing.description = goal.description
            existing.created_at = goal.created_at
            continue
        db.add(
            Goal(
                channel_id=channel.id,
                twitch_goal_id=goal.id,
                goal_type=goal.type,
                description=goal.description,
                current_amount=goal.current_amount,
                target_amount=goal.target_amount,
                created_at=goal.created_at,
            )
        )
        added += 1
    for goal_id, row in stored.items():
        if goal_id not in seen:  # goal ended since last connect
            db.delete(row)
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


def backfill_subscriptions(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Replace the current-subscriber snapshot from Helix. Affiliate-only, so
    this stays empty until the channel monetizes. Returns the snapshot size."""
    token = ensure_fresh_token(db, channel, client)
    records = get_subscriptions(channel.twitch_user_id, token, client)
    db.execute(delete(Subscription).where(Subscription.channel_id == channel.id))
    for record in records:
        db.add(
            Subscription(
                channel_id=channel.id,
                twitch_user_id=int(record.user_id),
                login=record.user_login,
                tier=record.tier,
                is_gift=record.is_gift,
                gifter_login=record.gifter_login,
            )
        )
    return len(records)


def backfill_bits_leaders(
    db: Session, channel: Channel, client: httpx.Client | None = None
) -> int:
    """Replace the all-time bits leaderboard snapshot from Helix (affiliate
    only). Returns the number of leaders stored."""
    token = ensure_fresh_token(db, channel, client)
    records = get_bits_leaderboard(token, client)
    db.execute(delete(BitsLeader).where(BitsLeader.channel_id == channel.id))
    for record in records:
        db.add(
            BitsLeader(
                channel_id=channel.id,
                login=record.user_login,
                rank=record.rank,
                score=record.score,
            )
        )
    return len(records)
