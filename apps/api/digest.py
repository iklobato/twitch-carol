"""Public (unauthenticated) unsubscribe link for the weekly/monthly email
digest. Same trust model as the email itself: whoever holds the link can turn
the sender off for that channel, nothing more.

GET only shows a confirm button; the POST is what unsubscribes. Mail security
scanners (Outlook Safe Links, corporate gateways) open every link in an email
before the reader does, so a GET that acted would unsubscribe people who never
clicked. The POST is also the RFC 8058 one-click target the mailer advertises
in List-Unsubscribe-Post: Gmail and Yahoo send it straight to this URL."""

from html import escape

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from apps.api.deps import DbSession
from core.crypto import read_unsubscribe_token
from core.i18n import t
from core.models import Channel, DigestPeriod

router = APIRouter(prefix="/api/digest")

VALID_PERIODS = {DigestPeriod.WEEKLY.value, DigestPeriod.MONTHLY.value}
PAGE_STYLE = "font-family:sans-serif"


def _channel_from_link(db: DbSession, token: str, period: str | None) -> Channel:
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
    return channel


@router.get("/unsubscribe", response_class=HTMLResponse)
def confirm_unsubscribe(
    request: Request,
    db: DbSession,
    token: str = Query(alias="t"),
    period: str | None = None,
) -> str:
    channel = _channel_from_link(db, token, period)
    question = t(channel.language, "digest.unsubscribeConfirm")
    button = t(channel.language, "digest.unsubscribeButton")
    # Relative on purpose: behind the App Platform proxy request.url reads
    # http://, and an absolute http action would post off the https page.
    action = escape(f"{request.url.path}?{request.url.query}")
    return (
        f'<form method="post" action="{action}" style="{PAGE_STYLE}">'
        f'<p>{question}</p><button type="submit">{button}</button></form>'
    )


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    db: DbSession, token: str = Query(alias="t"), period: str | None = None
) -> str:
    channel = _channel_from_link(db, token, period)
    if period in (None, DigestPeriod.WEEKLY.value):
        channel.digest_weekly = False
    if period in (None, DigestPeriod.MONTHLY.value):
        channel.digest_monthly = False
    db.commit()

    message = t(channel.language, "digest.unsubscribed")
    return f'<p style="{PAGE_STYLE}">{message}</p>'
