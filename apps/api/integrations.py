"""OAuth connect flow for external data sources. Today: StreamElements, so a
streamer clicks "Connect" in the app instead of pasting a JWT, and their tips
flow into the consolidated finance view."""

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from apps.api.deps import CurrentChannel, DbSession
from core.config import get_settings
from core.integrations.streamelements import (
    StreamElementsError,
    build_authorize_url,
    exchange_code,
    fetch_channel_id,
    oauth_header,
)
from core.integrations.tips import set_streamelements_oauth, sync_streamelements

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations")

SE_STATE_COOKIE = "se_oauth_state"
STATE_MAX_AGE_SECONDS = 600


def _secure_cookies() -> bool:
    return get_settings().public_base_url.startswith("https://")


@router.get("/streamelements/connect")
def connect(channel: CurrentChannel) -> RedirectResponse:
    if not get_settings().streamelements_client_id:
        raise HTTPException(
            status_code=503, detail="StreamElements OAuth not configured"
        )
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(build_authorize_url(state))
    response.set_cookie(
        SE_STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )
    return response


@router.get("/streamelements/callback")
def callback(
    request: Request,
    channel: CurrentChannel,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error is not None:
        raise HTTPException(
            status_code=400, detail=f"StreamElements authorization failed: {error}"
        )
    cookie_state = request.cookies.get(SE_STATE_COOKIE)
    if (
        not code
        or not state
        or not cookie_state
        or not secrets.compare_digest(state, cookie_state)
    ):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        token = exchange_code(code)
        account_id = fetch_channel_id(oauth_header(token.access_token))
    except StreamElementsError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err

    set_streamelements_oauth(db, channel, account_id, token)
    _sync_best_effort(db, channel)

    response = RedirectResponse("/")
    response.delete_cookie(SE_STATE_COOKIE)
    return response


def _sync_best_effort(db: DbSession, channel: CurrentChannel) -> None:
    """Pull tips on connect. Best-effort: a StreamElements hiccup must not fail
    the connect, and the next sync retries with the stored token."""
    try:
        summary = sync_streamelements(db, channel)
    except StreamElementsError:
        logger.exception("streamelements sync failed", extra={"channel_id": channel.id})
        return
    logger.info(
        "streamelements sync done: %s", summary, extra={"channel_id": channel.id}
    )
