"""Pure SQL-derived stream analytics shared by the actionable endpoint and
the analyze worker: viewer retention, audience dips, topic engagement facts.
No LLM here; these are the grounded numbers recommendations are built on.

`retention_and_dips` yields the bare numbers of a drop. `enrich_dips` (which
needs the db) layers the context that explains it: what you were saying (or
whether music was playing), what the chat was saying, whether an ad or a
category change caused it, and whether the audience came back.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import (
    ChatMessage,
    Event,
    SegmentKind,
    Stream,
    TranscriptSegment,
    ViewerSample,
)

DIP_MIN_DROP = 0.15
DIP_LOOKAHEAD = 5
DIP_MERGE_SECONDS = 120

# A drop shows up in the 60s viewer sample shortly AFTER its cause, so look a
# little back (and a touch forward) from the dip for the speech/event context.
CONTEXT_GAP_SECONDS = 120
CAUSE_AFTER_SECONDS = 30
RECOVERY_WINDOW = timedelta(minutes=5)
CHAT_WINDOW_SECONDS = 60
CHAT_SAMPLE = 3

AD_BREAK = "channel.ad_break.begin"
CHANNEL_UPDATE = "channel.update"
CAUSE_EVENT_TYPES = (AD_BREAK, CHANNEL_UPDATE)

SCENE_LABELS: dict[SegmentKind, str] = {
    SegmentKind.MUSIC: "tocando música",
    SegmentKind.SILENCE: "sem falar",
    SegmentKind.GUEST_CONVERSATION: "conversa com convidado",
}


@dataclass(frozen=True)
class Dip:
    at: datetime
    viewers_before: int
    viewers_after: int
    viewers_delta: int
    pct_drop: float
    # context (filled by enrich_dips; bare numbers leave these at their default)
    offset_seconds: int = 0
    speech_context: str | None = None
    scene: str | None = None
    cause: str | None = None
    recovered_to: int | None = None
    recovered_in_minutes: float | None = None
    chat_context: tuple[str, ...] = ()


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


def retention_and_dips(
    samples: list[ViewerSample],
    max_dips: int,
) -> tuple[Retention | None, list[Dip]]:
    """Bare numbers only: retention and the biggest audience drops. Call
    enrich_dips to add the context that explains each drop."""
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
                    viewers_delta=trough - before,
                    pct_drop=round(drop * 100, 1),
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


def _speech_and_scene(
    db: Session, stream_id: int, moment: datetime
) -> tuple[str | None, str | None]:
    """What was happening at the drop: the speech text if you were talking (or
    the nearest speech within the gap), and a scene label when a non-speech
    segment (music/silence/guest) overlapped the moment instead."""
    low = moment - timedelta(seconds=CONTEXT_GAP_SECONDS)
    high = moment + timedelta(seconds=CONTEXT_GAP_SECONDS)
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.stream_id == stream_id)
        .where(TranscriptSegment.ended_at >= low)
        .where(TranscriptSegment.started_at <= high)
        .order_by(TranscriptSegment.started_at)
    ).all()

    scene: str | None = None
    for segment in segments:
        if segment.started_at <= moment <= segment.ended_at:
            if segment.kind == SegmentKind.SPEECH and segment.text:
                return segment.text, None
            scene = SCENE_LABELS.get(segment.kind)
            break

    nearest = _nearest_speech(segments, moment)
    return nearest, scene


def _nearest_speech(
    segments: Sequence[TranscriptSegment], moment: datetime
) -> str | None:
    best_text: str | None = None
    best_gap = float("inf")
    for segment in segments:
        if segment.kind != SegmentKind.SPEECH or not segment.text:
            continue
        gap = min(
            abs((segment.started_at - moment).total_seconds()),
            abs((segment.ended_at - moment).total_seconds()),
        )
        if gap < best_gap:
            best_gap = gap
            best_text = segment.text
    return best_text


def dip_cause(db: Session, stream_id: int, moment: datetime) -> str | None:
    """The most likely trigger of a drop from the event timeline: an ad break
    (its duration) or a category change just before it. None if neither fired."""
    low = moment - timedelta(seconds=CONTEXT_GAP_SECONDS)
    high = moment + timedelta(seconds=CAUSE_AFTER_SECONDS)
    events = db.scalars(
        select(Event)
        .where(Event.stream_id == stream_id)
        .where(Event.type.in_(CAUSE_EVENT_TYPES))
        .where(Event.occurred_at >= low)
        .where(Event.occurred_at <= high)
        .order_by(Event.occurred_at.desc())
    ).all()
    ad = next((e for e in events if e.type == AD_BREAK), None)
    if ad is not None:
        return f"anúncio de {ad.amount}s" if ad.amount else "anúncio"
    for event in events:
        category = (event.payload or {}).get("category_name")
        if category:
            return f"troca para {category}"
    return None


def _recovery(samples: list[ViewerSample], dip: Dip) -> tuple[int | None, float | None]:
    """Did the audience come back? The best count within RECOVERY_WINDOW after
    the drop, and how many minutes it took. None when it never rose again."""
    after = [s for s in samples if dip.at < s.sampled_at <= dip.at + RECOVERY_WINDOW]
    if not after:
        return None, None
    best = max(after, key=lambda s: s.viewer_count)
    if best.viewer_count <= dip.viewers_after:
        return None, None
    minutes = round((best.sampled_at - dip.at).total_seconds() / 60, 1)
    return best.viewer_count, minutes


def _chat_around(db: Session, stream_id: int, moment: datetime) -> tuple[str, ...]:
    low = moment - timedelta(seconds=CHAT_WINDOW_SECONDS)
    high = moment + timedelta(seconds=CHAT_WINDOW_SECONDS)
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.stream_id == stream_id)
        .where(ChatMessage.sent_at >= low)
        .where(ChatMessage.sent_at <= high)
        .order_by(ChatMessage.sent_at)
        .limit(CHAT_SAMPLE)
    ).all()
    return tuple(f"{m.author_login}: {m.text}" for m in rows)


def enrich_dips(
    db: Session, stream: Stream, samples: list[ViewerSample], dips: list[Dip]
) -> list[Dip]:
    """Layer the explaining context onto each bare dip."""
    enriched: list[Dip] = []
    for dip in dips:
        speech, scene = _speech_and_scene(db, stream.id, dip.at)
        recovered_to, recovered_in = _recovery(samples, dip)
        enriched.append(
            replace(
                dip,
                offset_seconds=max(
                    int((dip.at - stream.started_at).total_seconds()), 0
                ),
                speech_context=speech,
                scene=scene,
                cause=dip_cause(db, stream.id, dip.at),
                recovered_to=recovered_to,
                recovered_in_minutes=recovered_in,
                chat_context=_chat_around(db, stream.id, dip.at),
            )
        )
    return enriched


def load_speech_segments(db: Session, stream_id: int) -> list[TranscriptSegment]:
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
