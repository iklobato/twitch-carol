"""Public (unauthenticated) endpoints. Aggregate platform stats for the landing
page, cached in-process because the landing is public and the counts run over
large tables; marketing numbers tolerate being a few minutes stale."""

import time

from fastapi import APIRouter
from pydantic import BaseModel

from apps.api.deps import DbSession
from core.metrics import platform_stats

router = APIRouter(prefix="/api")

STATS_TTL_SECONDS = 600  # 10 min


class PlatformStats(BaseModel):
    chat_messages: int
    streams_analyzed: int
    hours_captured: int
    segments_transcribed: int


_cached: PlatformStats | None = None
_cached_at = 0.0


@router.get("/stats")
def public_stats(db: DbSession) -> PlatformStats:
    global _cached, _cached_at
    now = time.monotonic()
    if _cached is None or now - _cached_at >= STATS_TTL_SECONDS:
        _cached = PlatformStats(**platform_stats(db))
        _cached_at = now
    return _cached
