"""Serves the /howto marketing page through the API, in the reader's language.

On DigitalOcean App Platform the static site cannot do extensionless URLs or
rewrites, so the bare /howto 404s while /howto.html works. Routing /howto to the
API lets the exact URL return the page. It also lets us pick the language:

- ?lang=pt|en on the URL wins and is remembered in a cookie;
- else the howto_lang cookie;
- else the browser's Accept-Language (en* -> en);
- else Portuguese (the default audience).

The page's screenshots-turned-HTML need no assets; everything is inline.
"""

import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

from apps.api.deps import DbSession
from core.models import CampaignRecipient

router = APIRouter()

SUPPORTED_LANGS = ("pt", "en")
DEFAULT_LANG = "pt"
LANG_COOKIE = "howto_lang"
LANG_COOKIE_MAX_AGE = 180 * 24 * 3600

# Cold-email attribution: the campaign link carries ?e=<token>, one token per
# recipient (see scripts/send_campaign_batch.py). The cookie carries it to the
# Twitch callback so a signup can be tied back to the person who was emailed.
SOURCE_PARAM = "e"
SOURCE_COOKIE = "si_src"
SOURCE_COOKIE_MAX_AGE = 30 * 24 * 3600
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,16}$")

# Local/dev reads the source files in the repo; the container image gets copies
# beside this module (see deploy/Dockerfile), because the API image does not
# include apps/web.
_SEARCH_DIRS = (
    Path(__file__).resolve().parents[2] / "apps" / "web" / "public",
    Path(__file__).resolve().parent,
)


def resolve_lang(request: Request) -> str:
    query = request.query_params.get("lang")
    if query in SUPPORTED_LANGS:
        return query
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie in SUPPORTED_LANGS:
        return cookie
    if request.headers.get("accept-language", "").strip().lower().startswith("en"):
        return "en"
    return DEFAULT_LANG


@lru_cache
def _howto_html(lang: str) -> str:
    for directory in _SEARCH_DIRS:
        path = directory / f"howto.{lang}.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"howto.{lang}.html not found next to the API")


def _attribute_visit(request: Request, response: Response, db: DbSession) -> None:
    """Counts the visit against the recipient the link belongs to. An unknown
    or malformed token is simply not us: no row, no cookie, no error."""
    token = request.query_params.get(SOURCE_PARAM, "")
    if not TOKEN_PATTERN.match(token):
        return
    recipient = db.scalar(select(CampaignRecipient).where(CampaignRecipient.token == token))
    if recipient is None:
        return
    recipient.visit_count += 1
    if recipient.visited_at is None:
        recipient.visited_at = datetime.now(UTC)
    db.commit()
    response.set_cookie(SOURCE_COOKIE, token, max_age=SOURCE_COOKIE_MAX_AGE, samesite="lax")


@router.get("/howto", response_class=HTMLResponse)
@router.get("/howto.html", response_class=HTMLResponse)
def howto(request: Request, db: DbSession) -> HTMLResponse:
    lang = resolve_lang(request)
    response = HTMLResponse(_howto_html(lang))
    # Remember an explicit choice so the toggle sticks across pages.
    if request.query_params.get("lang") in SUPPORTED_LANGS:
        response.set_cookie(LANG_COOKIE, lang, max_age=LANG_COOKIE_MAX_AGE, samesite="lax")
    _attribute_visit(request, response, db)
    return response
