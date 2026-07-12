"""Next-live estimation from a channel's streaming history.

The transcription queue's hard rule: reports must be ready before the
channel's next live. Priority = estimated_next_live - now, ascending.
"""

from datetime import UTC, datetime, time, timedelta
from statistics import median

HISTORY_LIMIT = 20
FALLBACK_INTERVAL = timedelta(hours=24)
SEARCH_DAYS = 8


def estimate_next_live(now: datetime, past_starts: list[datetime]) -> datetime:
    """Median start time per weekday over recent history; the next matching
    weekday/time after now is the estimate. Falls back to now + 24h."""
    if not past_starts:
        return now + FALLBACK_INTERVAL

    minutes_by_weekday: dict[int, list[int]] = {}
    for started_at in past_starts:
        local = started_at.astimezone(UTC)
        minutes_by_weekday.setdefault(local.weekday(), []).append(
            local.hour * 60 + local.minute
        )

    candidates = []
    for day_offset in range(SEARCH_DAYS):
        day = (now + timedelta(days=day_offset)).date()
        day_minutes = minutes_by_weekday.get(day.weekday())
        if day_minutes is None:
            continue
        typical = int(median(day_minutes))
        candidate = datetime.combine(
            day, time(hour=typical // 60, minute=typical % 60), tzinfo=UTC
        )
        if candidate > now:
            candidates.append(candidate)
    if candidates:
        return min(candidates)
    return max(past_starts) + FALLBACK_INTERVAL
