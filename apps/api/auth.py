import logging
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from apps.api.deps import SESSION_COOKIE, DbSession
from core.backfill import (
    backfill_bits_leaders,
    backfill_goals,
    backfill_subscriptions,
    backfill_videos,
    backfill_vips,
)
from core.channels import upsert_channel
from core.config import get_settings
from core.crypto import SESSION_MAX_AGE_SECONDS, create_session_token
from core.eventsub import sync_channel_subscriptions
from core.follower_sync import request_sync
from core.models import Channel
from core.twitch import TwitchAuthError, build_authorize_url, exchange_code, get_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

STATE_COOKIE = "oauth_state"
STATE_MAX_AGE_SECONDS = 600

# Each is a single Helix call, cheap enough to keep in the login request.
BACKFILL_STEPS = (
    ("videos", backfill_videos),
    ("vips", backfill_vips),
    ("goals", backfill_goals),
    ("subs", backfill_subscriptions),
    ("bits", backfill_bits_leaders),
)


def _secure_cookies() -> bool:
    return get_settings().public_base_url.startswith("https://")


@router.get("/login")
def login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(build_authorize_url(state))
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error is not None:
        raise HTTPException(
            status_code=400, detail=f"Twitch authorization failed: {error}"
        )
    cookie_state = request.cookies.get(STATE_COOKIE)
    if (
        not code
        or not state
        or not cookie_state
        or not secrets.compare_digest(state, cookie_state)
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        grant = exchange_code(code)
        user = get_user(grant.access_token)
    except TwitchAuthError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err

    channel = upsert_channel(db, user, grant)
    db.commit()
    _backfill_best_effort(db, channel)
    _sync_eventsub_best_effort(channel)

    response = RedirectResponse("/")
    response.delete_cookie(STATE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(channel.id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )
    return response


def _backfill_best_effort(db: DbSession, channel: Channel) -> None:
    """Pull the one-call histories on connect, then hand followers to the worker.

    Each step commits on its own. Sharing one commit meant a channel that failed
    on the first step connected with nothing at all: no VIPs, no goals, no
    subscriptions, none of which had anything to do with what broke.

    Followers are NOT fetched here. Walking a large channel takes hundreds of
    Helix calls, which is not something an OAuth redirect can wait for; clearing
    followers_synced_at puts the channel at the front of the sync worker's queue.
    """
    for name, step in BACKFILL_STEPS:
        try:
            count = step(db, channel)
            db.commit()
        except (httpx.HTTPError, TwitchAuthError):
            db.rollback()
            logger.exception(
                "backfill step %s failed", name, extra={"channel_id": channel.id}
            )
            continue
        logger.info("backfill %s: %d", name, count, extra={"channel_id": channel.id})
    request_sync(channel)
    db.commit()


def _sync_eventsub_best_effort(channel: Channel) -> None:
    """Twitch only accepts HTTPS webhook callbacks, so local dev skips this;
    the simulator drives the webhook endpoint directly instead."""
    settings = get_settings()
    if (
        not settings.public_base_url.startswith("https://")
        or not settings.twitch_eventsub_secret
    ):
        logger.info(
            "eventsub sync skipped (needs https PUBLIC_BASE_URL and secret)",
            extra={"channel_id": channel.id},
        )
        return
    try:
        summary = sync_channel_subscriptions(channel)
    except (httpx.HTTPError, TwitchAuthError):
        logger.exception("eventsub sync failed", extra={"channel_id": channel.id})
        return
    logger.info("eventsub sync done: %s", summary, extra={"channel_id": channel.id})


@router.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/")
    response.delete_cookie(SESSION_COOKIE)
    return response
