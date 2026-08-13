"""Serves the /howto marketing page through the API, in the reader's language.

On DigitalOcean App Platform the static site cannot do extensionless URLs or
rewrites, so the bare /howto 404s while /howto.html works. Routing /howto to the
API lets the exact URL return the page. It also lets us pick the language:

- ?lang=pt|en on the URL wins and is remembered in a cookie;
- else the howto_lang cookie;
- else the signed-in channel's own language (channels.language), so the page
  matches the language the dashboard is already showing them;
- else the browser's Accept-Language (pt* -> pt);
- else English, the language the product is served in. Same rule as the web app,
  so a reader whose browser is neither pt nor en sees one language on the sales
  page and in the dashboard, not two.

The page's screenshots-turned-HTML need no assets; everything is inline.
"""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from apps.api.deps import OptionalChannel
from core.i18n import resolve as resolve_language
from core.models import Channel

router = APIRouter()

SUPPORTED_LANGS = ("pt", "en")
DEFAULT_LANG = "en"
LANG_COOKIE = "howto_lang"
LANG_COOKIE_MAX_AGE = 180 * 24 * 3600

# Local/dev reads the source files in the repo; the container image gets copies
# beside this module (see deploy/Dockerfile), because the API image does not
# include apps/web.
_SEARCH_DIRS = (
    Path(__file__).resolve().parents[2] / "apps" / "web" / "public",
    Path(__file__).resolve().parent,
)


def resolve_lang(request: Request, channel: Channel | None = None) -> str:
    query = request.query_params.get("lang")
    if query in SUPPORTED_LANGS:
        return query
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie in SUPPORTED_LANGS:
        return cookie
    if channel is not None:
        return resolve_language(channel.language)
    if request.headers.get("accept-language", "").strip().lower().startswith("pt"):
        return "pt"
    return DEFAULT_LANG


@lru_cache
def _howto_html(lang: str) -> str:
    for directory in _SEARCH_DIRS:
        path = directory / f"howto.{lang}.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"howto.{lang}.html not found next to the API")


@router.get("/howto", response_class=HTMLResponse)
@router.get("/howto.html", response_class=HTMLResponse)
def howto(request: Request, channel: OptionalChannel = None) -> HTMLResponse:
    lang = resolve_lang(request, channel)
    response = HTMLResponse(_howto_html(lang))
    # Remember an explicit choice so the toggle sticks across pages.
    if request.query_params.get("lang") in SUPPORTED_LANGS:
        response.set_cookie(LANG_COOKIE, lang, max_age=LANG_COOKIE_MAX_AGE, samesite="lax")
    return response
