"""Public (unauthenticated) unsubscribe link for the weekly/monthly email
digest. Same trust model as the email itself: whoever holds the link can turn
the sender off for that channel, nothing more."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from apps.api.deps import DbSession
from core.crypto import read_unsubscribe_token
from core.i18n import t
from core.models import Channel, DigestPeriod

router = APIRouter(prefix="/api/digest")

VALID_PERIODS = {DigestPeriod.WEEKLY.value, DigestPeriod.MONTHLY.value}


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    db: DbSession, token: str = Query(alias="t"), period: str | None = None
) -> str:
    if period is not None and period not in VALID_PERIODS:
        raise HTTPException(
            status_code=422, detail=f"period must be one of {VALID_PERIODS}"
        )
    channel_id = read_unsubscribe_token(token)
    if channel_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    if period in (None, DigestPeriod.WEEKLY.value):
        channel.digest_weekly = False
    if period in (None, DigestPeriod.MONTHLY.value):
        channel.digest_monthly = False
    db.commit()

    message = t(channel.language, "digest.unsubscribed")
    return f'<p style="font-family:sans-serif">{message}</p>'
