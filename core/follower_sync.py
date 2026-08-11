"""Keeps a channel's follower list, its real total and its unfollows in step
with Twitch, one committed page at a time.

This work used to run inline inside the OAuth callback, and it cost real data.
Measured in production on 2026-08-11: a channel with 41,605 followers held
exactly 20,000 rows (the page cap of the day) and not one enriched profile, and
another with 26,349 followers held nothing at all, not even its VIPs. Both had
the same cause. Everything was fetched under a single commit at the very end, so
one slow or rate-limited Helix response threw away every call already spent.

The rules that follow from that:

- one page per commit, so a failure costs a page and never the run
- the cursor lives in the database, so a restart resumes instead of restarting
- the follower count shown to a streamer is the total Twitch reports, never a
  count of our own rows, which drifts both ways
- a follower is only recorded as gone after being confirmed one by one
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from core.channels import ensure_fresh_token
from core.models import Channel, Follower, Unfollow, UnfollowReason
from core.twitch import (
    FollowerRecord,
    get_channels_by_ids,
    get_followers_page,
    get_users_by_ids,
)

logger = logging.getLogger(__name__)

# Helix allows 800 calls a minute per client id, and that budget is shared with
# the live-capture path, which must never lose a call to a follower sync. Pacing
# at five a second spends 300 a minute and still walks the largest channel we
# have (41,605 followers, 417 pages) in about three minutes.
PACE_SECONDS = 0.2
SYNC_INTERVAL = timedelta(hours=6)
# Each candidate costs a call to confirm, so a pass that somehow turns up a huge
# candidate list stops here and leaves the rest to the next pass. What was
# deferred is logged and returned: a cap that hides what it dropped reads as
# "nothing left to do".
UNFOLLOW_CONFIRM_LIMIT = 200


@dataclass(frozen=True)
class SyncResult:
    total: int
    pages: int
    added: int
    enriched: int
    unfollowed: int
    accounts_gone: int
    unfollows_deferred: int
    completed: bool


def channels_due(db: Session, now: datetime) -> list[Channel]:
    """Channels needing a pass, longest-waiting first.

    A null `followers_synced_at` sorts first, which is how a fresh connect and a
    re-login jump the queue: the login hands the work over by clearing that
    column instead of doing it inline.
    """
    return list(
        db.scalars(
            select(Channel)
            .where(
                or_(
                    Channel.followers_synced_at.is_(None),
                    Channel.followers_synced_at < now - SYNC_INTERVAL,
                )
            )
            .order_by(Channel.followers_synced_at.asc().nulls_first())
        )
    )


def request_sync(channel: Channel) -> None:
    """Put a channel at the front of the sync queue. The caller commits."""
    channel.followers_synced_at = None


def sync_channel(
    db: Session,
    channel: Channel,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult:
    """Walk Twitch's follower list for one channel, committing every page."""
    token = ensure_fresh_token(db, channel, client)

    if channel.follower_sync_cursor is None or channel.follower_sync_started_at is None:
        channel.follower_sync_started_at = datetime.now(UTC)
        channel.follower_sync_cursor = None
    pass_started_at = channel.follower_sync_started_at

    cursor = channel.follower_sync_cursor
    total = channel.follower_total or 0
    pages = 0
    added = 0
    try:
        while True:
            page = get_followers_page(channel.twitch_user_id, token, cursor, client)
            pages += 1
            total = page.total
            added += _store_page(db, channel.id, page.followers, pass_started_at)
            cursor = page.cursor
            channel.follower_sync_cursor = cursor
            channel.follower_total = total
            channel.follower_sync_error = None
            db.commit()
            if cursor is None:
                break
            sleep(PACE_SECONDS)
    except Exception as err:  # noqa: BLE001 - any failure must leave the walk resumable
        db.rollback()
        # The committed pages keep their rows and the stored cursor points at the
        # next one, so a retry costs a page rather than the whole walk.
        channel.follower_sync_error = f"{type(err).__name__}: {err}"
        db.commit()
        logger.warning(
            "follower sync interrupted after %d pages: %s",
            pages,
            channel.follower_sync_error,
            extra={"channel_id": channel.id},
        )
        return SyncResult(total, pages, added, 0, 0, 0, 0, completed=False)

    enriched = _enrich_best_effort(db, channel, client, sleep)
    gone = _reconcile_unfollows(db, channel, pass_started_at, client, sleep)
    channel.follower_sync_cursor = None
    channel.follower_sync_started_at = None
    channel.followers_synced_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "follower sync done: total %d, %d pages, %d new, %d enriched, "
        "%d unfollowed, %d gone",
        total,
        pages,
        added,
        enriched,
        gone.unfollowed,
        gone.accounts_gone,
        extra={"channel_id": channel.id},
    )
    return SyncResult(
        total,
        pages,
        added,
        enriched,
        gone.unfollowed,
        gone.accounts_gone,
        gone.deferred,
        completed=True,
    )


def _enrich_best_effort(
    db: Session,
    channel: Channel,
    client: httpx.Client | None,
    sleep: Callable[[float], None],
) -> int:
    """Enrich profiles, tolerating a Helix failure.

    Each batch is already committed, so a failure here keeps what it managed and
    the rows it did not reach still have a null stamp, which is exactly what the
    next pass looks for. The pass is still stamped as done afterwards, otherwise a
    persistently failing enrichment would spin this channel forever.
    """
    try:
        return enrich_followers(db, channel, client, sleep) + enrich_streamer_followers(
            db, channel, client, sleep
        )
    except Exception as err:  # noqa: BLE001 - enrichment must not fail the walk
        db.rollback()
        channel.follower_sync_error = f"enrichment: {type(err).__name__}: {err}"
        logger.warning(
            "follower enrichment incomplete: %s",
            channel.follower_sync_error,
            extra={"channel_id": channel.id},
        )
        return 0


def _store_page(
    db: Session,
    channel_id: int,
    records: list[FollowerRecord],
    pass_started_at: datetime,
) -> int:
    """Insert the new rows of one page and mark every row on it as seen.

    Looked up a page at a time rather than loading the channel's whole follower
    set up front: the biggest channel here has 41,605 of them, and holding that
    many live ORM objects is what the old enrichment did before it fell over.
    """
    user_ids = [int(record.user_id) for record in records]
    existing = {
        row.twitch_user_id: row
        for row in db.scalars(
            select(Follower)
            .where(Follower.channel_id == channel_id)
            .where(Follower.twitch_user_id.in_(user_ids))
        )
    }
    added = 0
    for record in records:
        user_id = int(record.user_id)
        follower = existing.get(user_id)
        if follower is None:
            follower = Follower(
                channel_id=channel_id,
                twitch_user_id=user_id,
                login=record.user_login,
                followed_at=record.followed_at,
            )
            db.add(follower)
            added += 1
        else:
            follower.login = record.user_login
        follower.last_seen_at = pass_started_at
    return added


ENRICH_BATCH_SIZE = 100
STREAMER_TYPES = ("affiliate", "partner")


def enrich_followers(
    db: Session,
    channel: Channel,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fill profile fields (name, avatar, bio, broadcaster_type, account age) for
    followers not yet enriched, via Helix Get Users.

    Commits each batch. The version that committed once at the end left a
    20,000-follower channel with every profile field empty, which is what made
    its composition, cohort and collab panels read as zero.
    """
    enriched = 0
    while True:
        batch = _pending_batch(db, Follower.enriched_at, channel.id)
        if not batch:
            return enriched
        by_id = {follower.twitch_user_id: follower for follower in batch}
        now = datetime.now(UTC)
        for profile in get_users_by_ids(list(by_id), client):
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
        # Stamp the rest of the batch too: an id Twitch dropped (banned, deleted)
        # must not be asked about forever, or the batch never empties and this
        # loop never ends.
        for follower in batch:
            if follower.enriched_at is None:
                follower.enriched_at = now
        db.commit()
        sleep(PACE_SECONDS)


def enrich_streamer_followers(
    db: Session,
    channel: Channel,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fill category and language for followers who are themselves streamers, via
    Helix Get Channel Information, to score collab fit. Commits each batch."""
    enriched = 0
    while True:
        batch = _pending_batch(
            db,
            Follower.streamer_enriched_at,
            channel.id,
            only_streamers=True,
        )
        if not batch:
            return enriched
        by_id = {follower.twitch_user_id: follower for follower in batch}
        now = datetime.now(UTC)
        for info in get_channels_by_ids(list(by_id), client):
            follower = by_id.get(int(info.broadcaster_id))
            if follower is None:
                continue
            follower.stream_category = info.game_name or None
            follower.stream_language = info.broadcaster_language or None
            follower.streamer_enriched_at = now
            enriched += 1
        for follower in batch:
            if follower.streamer_enriched_at is None:
                follower.streamer_enriched_at = now
        db.commit()
        sleep(PACE_SECONDS)


def _pending_batch(
    db: Session,
    stamp: InstrumentedAttribute,
    channel_id: int,
    only_streamers: bool = False,
) -> list[Follower]:
    """One batch of followers still missing `stamp`.

    Queried a batch at a time rather than loading every pending row: this used to
    materialise the channel's entire follower set as live ORM objects, which for
    41,605 of them is a lot of memory for no gain.
    """
    query = (
        select(Follower)
        .where(Follower.channel_id == channel_id)
        .where(stamp.is_(None))
        .limit(ENRICH_BATCH_SIZE)
    )
    if only_streamers:
        query = query.where(Follower.broadcaster_type.in_(STREAMER_TYPES))
    return list(db.scalars(query))


@dataclass(frozen=True)
class _GoneCount:
    unfollowed: int
    accounts_gone: int
    deferred: int


def _reconcile_unfollows(
    db: Session,
    channel: Channel,
    pass_started_at: datetime,
    client: httpx.Client | None,
    sleep: Callable[[float], None],
) -> _GoneCount:
    """Turn rows a completed pass never saw into unfollows.

    Only reachable once a pass walked all the way to the end, and even then every
    candidate is confirmed individually. Cursor pagination over a list people are
    joining and leaving can skip a row, and dropping a real follower over a
    paging artefact is worse than counting one for another six hours.

    Rows whose `followed_at` is not older than the pass are left alone: they
    arrived while the walk was already running (the live channel.follow event
    writes them), so the walk never had a chance to see them.
    """
    candidates = list(
        db.scalars(
            select(Follower)
            .where(Follower.channel_id == channel.id)
            .where(Follower.followed_at < pass_started_at)
            .where(
                or_(
                    Follower.last_seen_at.is_(None),
                    Follower.last_seen_at < pass_started_at,
                )
            )
        )
    )
    if not candidates:
        return _GoneCount(0, 0, 0)

    deferred = max(0, len(candidates) - UNFOLLOW_CONFIRM_LIMIT)
    if deferred:
        logger.info(
            "%d unfollow candidates deferred to the next pass (limit %d)",
            deferred,
            UNFOLLOW_CONFIRM_LIMIT,
            extra={"channel_id": channel.id},
        )
    batch = candidates[:UNFOLLOW_CONFIRM_LIMIT]
    alive = _still_existing_accounts(batch, client)

    token = ensure_fresh_token(db, channel, client)
    unfollowed = 0
    accounts_gone = 0
    now = datetime.now(UTC)
    for follower in batch:
        if follower.twitch_user_id not in alive:
            _record_gone(db, channel.id, follower, now, UnfollowReason.ACCOUNT_GONE)
            accounts_gone += 1
            continue
        sleep(PACE_SECONDS)
        if _still_follows(
            channel.twitch_user_id, follower.twitch_user_id, token, client
        ):
            # A paging artefact, not a departure. Stamp it so the next pass does
            # not ask about the same person again.
            follower.last_seen_at = pass_started_at
            continue
        _record_gone(db, channel.id, follower, now, UnfollowReason.UNFOLLOWED)
        unfollowed += 1
    db.commit()
    return _GoneCount(unfollowed, accounts_gone, deferred)


def _still_existing_accounts(
    followers: list[Follower], client: httpx.Client | None
) -> set[int]:
    """Ids Twitch still knows. A banned or deleted account also drops out of the
    follower list, and telling a streamer that person unfollowed them is simply
    wrong, so the two are separated before anything is written down."""
    profiles = get_users_by_ids([f.twitch_user_id for f in followers], client)
    return {int(profile.id) for profile in profiles}


def _still_follows(
    broadcaster_id: int,
    user_id: int,
    token: str,
    client: httpx.Client | None,
) -> bool:
    """Ask Twitch about this one follow. Get Channel Followers takes a user_id and
    answers for exactly that person, so this is a direct check rather than an
    inference from a list that moved under us."""
    page = get_followers_page(broadcaster_id, token, None, client, user_id=user_id)
    return any(int(row.user_id) == user_id for row in page.followers)


def _record_gone(
    db: Session,
    channel_id: int,
    follower: Follower,
    detected_at: datetime,
    reason: UnfollowReason,
) -> None:
    db.add(
        Unfollow(
            channel_id=channel_id,
            twitch_user_id=follower.twitch_user_id,
            login=follower.login,
            display_name=follower.display_name,
            profile_image_url=follower.profile_image_url,
            followed_at=follower.followed_at,
            detected_at=detected_at,
            reason=reason,
        )
    )
    db.delete(follower)
