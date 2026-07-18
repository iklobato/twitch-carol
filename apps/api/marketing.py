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

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

SUPPORTED_LANGS = ("pt", "en")
DEFAULT_LANG = "pt"
LANG_COOKIE = "howto_lang"
LANG_COOKIE_MAX_AGE = 180 * 24 * 3600

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


@router.get("/howto", response_class=HTMLResponse)
@router.get("/howto.html", response_class=HTMLResponse)
def howto(request: Request) -> HTMLResponse:
    lang = resolve_lang(request)
    response = HTMLResponse(_howto_html(lang))
    # Remember an explicit choice so the toggle sticks across pages.
    if request.query_params.get("lang") in SUPPORTED_LANGS:
        response.set_cookie(
            LANG_COOKIE, lang, max_age=LANG_COOKIE_MAX_AGE, samesite="lax"
        )
    return response
