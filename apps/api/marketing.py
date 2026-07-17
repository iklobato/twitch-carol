"""Serves the /howto marketing page through the API.

On DigitalOcean App Platform the static site cannot do extensionless URLs or
rewrites, so the bare /howto 404s while /howto.html works. Routing /howto to the
API lets the exact URL return the same page the static build ships. The page's
screenshots live under /previews (served by the static site) so they stay
outside the /howto route prefix and are not swallowed by this route.
"""

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# Local/dev reads the source file in the repo; the container image gets a copy
# beside this module (see deploy/Dockerfile), because the API image does not
# include apps/web.
_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "apps" / "web" / "public" / "howto.html",
    Path(__file__).resolve().parent / "howto.html",
)


@lru_cache
def _howto_html() -> str:
    for path in _CANDIDATES:
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("howto.html not found next to the API")


@router.get("/howto", response_class=HTMLResponse)
@router.get("/howto.html", response_class=HTMLResponse)
def howto() -> HTMLResponse:
    return HTMLResponse(_howto_html())
