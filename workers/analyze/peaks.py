"""Chat-rate peak detection. All numbers come from SQL buckets; the LLM only
ever explains windows that were computed here (product rule 2)."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import delete
from sqlalchemy.orm import Session

from core.metrics import BUCKET_SECONDS, chat_rate_buckets
from core.models import Peak, Stream

logger = logging.getLogger(__name__)
METRIC_CHAT_RATE = "chat_rate"
TOP_PEAKS = 5
# A bucket is a peak candidate when it exceeds both the relative lift over the
# stream's median rate and an absolute floor (tiny streams are all noise).
MIN_LIFT = 2.0
MIN_MESSAGES_PER_BUCKET = 10


@dataclass(frozen=True)
class PeakWindow:
    start: datetime
    end: datetime
    score: float


def detect_peaks(
    buckets: list[tuple[datetime, int]], top_n: int = TOP_PEAKS
) -> list[PeakWindow]:
    if not buckets:
        return []
    baseline = max(median(count for _, count in buckets), 1.0)
    threshold = max(baseline * MIN_LIFT, MIN_MESSAGES_PER_BUCKET)

    windows: list[PeakWindow] = []
    current: PeakWindow | None = None
    for start, count in buckets:
        end = start + timedelta(seconds=BUCKET_SECONDS)
        if count < threshold:
            current = None
            continue
        score = count / baseline
        if current is not None and start == current.end:
            current = PeakWindow(current.start, end, max(current.score, score))
            windows[-1] = current
            continue
        current = PeakWindow(start, end, score)
        windows.append(current)

    return sorted(windows, key=lambda w: w.score, reverse=True)[:top_n]


def compute_and_store_peaks(db: Session, stream: Stream) -> list[Peak]:
    """Idempotent: recomputes and replaces the stream's peaks."""
    db.execute(delete(Peak).where(Peak.stream_id == stream.id))
    windows = detect_peaks(chat_rate_buckets(db, stream.id))
    peaks = [
        Peak(
            stream_id=stream.id,
            window_start=window.start,
            window_end=window.end,
            metric=METRIC_CHAT_RATE,
            score=round(window.score, 2),
        )
        for window in windows
    ]
    db.add_all(peaks)
    db.flush()
    logger.info("peaks computed: %d", len(peaks), extra={"stream_id": stream.id})
    return peaks
