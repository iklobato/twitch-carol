"""Pure SQL-derived stream analytics shared by the actionable endpoint and
the analyze worker: viewer retention, audience dips, topic engagement facts.
No LLM here; these are the grounded numbers recommendations are built on."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Stream, TranscriptSegment, ViewerSample

DIP_MIN_DROP = 0.15
DIP_LOOKAHEAD = 5
DIP_MERGE_SECONDS = 120


@dataclass(frozen=True)
class Dip:
    at: datetime
    viewers_before: int
    viewers_after: int
    pct_drop: float
    speech_context: str | None


@dataclass(frozen=True)
class Retention:
    peak_viewers: int
    final_viewers: int
    retained_pct: float
    biggest_drop_at: datetime | None


def load_viewer_samples(db: Session, stream_id: int) -> list[ViewerSample]:
    return list(
        db.scalars(
            select(ViewerSample)
            .where(ViewerSample.stream_id == stream_id)
            .order_by(ViewerSample.sampled_at)
        )
    )


def _speech_at(segments: list[TranscriptSegment], moment: datetime) -> str | None:
    for segment in segments:
        if segment.started_at <= moment <= segment.ended_at and segment.text:
            return segment.text
    return None


def retention_and_dips(
    samples: list[ViewerSample],
    speech: list[TranscriptSegment],
    max_dips: int,
) -> tuple[Retention | None, list[Dip]]:
    if not samples:
        return None, []
    counts = [s.viewer_count for s in samples]
    peak = max(counts)
    final = counts[-1]

    biggest_drop_at: datetime | None = None
    biggest_drop = 0.0
    dips: list[Dip] = []
    for index in range(len(samples) - 1):
        before = counts[index]
        if before <= 0:
            continue
        window = counts[index + 1 : index + 1 + DIP_LOOKAHEAD]
        trough = min(window) if window else before
        drop = (before - trough) / before
        if drop > biggest_drop:
            biggest_drop = drop
            biggest_drop_at = samples[index].sampled_at
        if drop >= DIP_MIN_DROP:
            dips.append(
                Dip(
                    at=samples[index].sampled_at,
                    viewers_before=before,
                    viewers_after=trough,
                    pct_drop=round(drop * 100, 1),
                    speech_context=_speech_at(speech, samples[index].sampled_at),
                )
            )

    dips.sort(key=lambda dip: dip.pct_drop, reverse=True)
    kept: list[Dip] = []
    for dip in dips:
        if all(
            abs((dip.at - other.at).total_seconds()) > DIP_MERGE_SECONDS
            for other in kept
        ):
            kept.append(dip)
        if len(kept) >= max_dips:
            break

    retention = Retention(
        peak_viewers=peak,
        final_viewers=final,
        retained_pct=round(final / peak * 100, 1) if peak else 0.0,
        biggest_drop_at=biggest_drop_at if biggest_drop >= DIP_MIN_DROP else None,
    )
    return retention, kept


def load_speech_segments(db: Session, stream_id: int) -> list[TranscriptSegment]:
    from core.models import SegmentKind

    return list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.stream_id == stream_id)
            .where(TranscriptSegment.kind == SegmentKind.SPEECH)
            .order_by(TranscriptSegment.started_at)
        )
    )


def stream_duration_minutes(stream: Stream) -> float:
    ended_at = stream.ended_at if stream.ended_at is not None else stream.started_at
    return max((ended_at - stream.started_at).total_seconds() / 60, 1)
