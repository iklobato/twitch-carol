"""Actionable insights for a stream: audience drop-offs, retention, clip
suggestions (from computed peaks) and unanswered chat questions. All SQL/
derived; the LLM is not involved here."""

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dashboard import _owned_stream
from apps.api.deps import CurrentChannel, DbSession
from core.models import (
    ChatMessage,
    Peak,
    SegmentKind,
    Stream,
    TranscriptSegment,
    ViewerSample,
)

router = APIRouter(prefix="/api")

DIP_MIN_DROP = 0.15  # a >=15% viewer fall is worth flagging
DIP_LOOKAHEAD = 5  # samples (minutes) to look ahead for the trough
MAX_DIPS = 3
MAX_CLIPS = 5
# a chat question is "unanswered" if the streamer wasn't speaking in this window
ANSWER_WINDOW = timedelta(seconds=90)
MAX_QUESTIONS_SCANNED = 500
MAX_QUESTION_SAMPLES = 8


class ViewerDip(BaseModel):
    at: datetime
    viewers_before: int
    viewers_after: int
    pct_drop: float
    speech_context: str | None


class Retention(BaseModel):
    peak_viewers: int
    final_viewers: int
    retained_pct: float
    biggest_drop_at: datetime | None


class ClipSuggestion(BaseModel):
    window_start: datetime
    window_end: datetime
    offset_seconds: int
    offset_label: str
    score: float


class QuestionSample(BaseModel):
    sent_at: datetime
    author_login: str
    text: str


class ActionableOut(BaseModel):
    retention: Retention | None
    dips: list[ViewerDip]
    clips: list[ClipSuggestion]
    unanswered_questions_count: int
    unanswered_questions: list[QuestionSample]


def _offset_label(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s"


def _speech_at(segments: list[TranscriptSegment], moment: datetime) -> str | None:
    for segment in segments:
        if segment.started_at <= moment <= segment.ended_at and segment.text:
            return segment.text
    return None


def _retention_and_dips(
    samples: list[ViewerSample], speech: list[TranscriptSegment]
) -> tuple[Retention | None, list[ViewerDip]]:
    if not samples:
        return None, []
    counts = [s.viewer_count for s in samples]
    peak = max(counts)
    final = counts[-1]

    biggest_drop_at = None
    biggest_drop = 0.0
    dips: list[ViewerDip] = []
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
                ViewerDip(
                    at=samples[index].sampled_at,
                    viewers_before=before,
                    viewers_after=trough,
                    pct_drop=round(drop * 100, 1),
                    speech_context=_speech_at(speech, samples[index].sampled_at),
                )
            )

    dips.sort(key=lambda dip: dip.pct_drop, reverse=True)
    # drop near-duplicates (dips within 2 min of a stronger one)
    kept: list[ViewerDip] = []
    for dip in dips:
        if all(abs((dip.at - other.at).total_seconds()) > 120 for other in kept):
            kept.append(dip)
        if len(kept) >= MAX_DIPS:
            break

    retention = Retention(
        peak_viewers=peak,
        final_viewers=final,
        retained_pct=round(final / peak * 100, 1) if peak else 0.0,
        biggest_drop_at=biggest_drop_at if biggest_drop >= DIP_MIN_DROP else None,
    )
    return retention, kept


def _clip_suggestions(db: Session, stream: Stream) -> list[ClipSuggestion]:
    peaks = db.scalars(
        select(Peak)
        .where(Peak.stream_id == stream.id)
        .order_by(Peak.score.desc())
        .limit(MAX_CLIPS)
    ).all()
    clips = []
    for peak in peaks:
        offset = int((peak.window_start - stream.started_at).total_seconds())
        clips.append(
            ClipSuggestion(
                window_start=peak.window_start,
                window_end=peak.window_end,
                offset_seconds=offset,
                offset_label=_offset_label(max(offset, 0)),
                score=peak.score,
            )
        )
    return clips


def _unanswered_questions(
    db: Session, stream: Stream, speech: list[TranscriptSegment]
) -> tuple[int, list[QuestionSample]]:
    questions = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.stream_id == stream.id)
        .where(ChatMessage.text.like("%?%"))
        .order_by(ChatMessage.sent_at)
        .limit(MAX_QUESTIONS_SCANNED)
    ).all()

    def answered(moment: datetime) -> bool:
        window_end = moment + ANSWER_WINDOW
        return any(
            segment.started_at < window_end and segment.ended_at > moment
            for segment in speech
        )

    unanswered = [q for q in questions if not answered(q.sent_at)]
    samples = [
        QuestionSample(sent_at=q.sent_at, author_login=q.author_login, text=q.text)
        for q in unanswered[-MAX_QUESTION_SAMPLES:]
    ]
    return len(unanswered), samples


@router.get("/streams/{stream_id}/actionable")
def stream_actionable(
    stream_id: int, channel: CurrentChannel, db: DbSession
) -> ActionableOut:
    stream = _owned_stream(db, channel, stream_id)
    samples = list(
        db.scalars(
            select(ViewerSample)
            .where(ViewerSample.stream_id == stream.id)
            .order_by(ViewerSample.sampled_at)
        )
    )
    speech = list(
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.stream_id == stream.id)
            .where(TranscriptSegment.kind == SegmentKind.SPEECH)
            .order_by(TranscriptSegment.started_at)
        )
    )
    retention, dips = _retention_and_dips(samples, speech)
    count, question_samples = _unanswered_questions(db, stream, speech)
    return ActionableOut(
        retention=retention,
        dips=dips,
        clips=_clip_suggestions(db, stream),
        unanswered_questions_count=count,
        unanswered_questions=question_samples,
    )
