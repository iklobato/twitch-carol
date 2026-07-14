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
from core.analytics import load_speech_segments, load_viewer_samples, retention_and_dips
from core.models import ChatMessage, Peak, Stream, TranscriptSegment

router = APIRouter(prefix="/api")

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
    samples = load_viewer_samples(db, stream.id)
    speech = load_speech_segments(db, stream.id)
    retention, dips = retention_and_dips(samples, speech, MAX_DIPS)
    count, question_samples = _unanswered_questions(db, stream, speech)
    return ActionableOut(
        retention=Retention(**vars(retention)) if retention else None,
        dips=[ViewerDip(**vars(dip)) for dip in dips],
        clips=_clip_suggestions(db, stream),
        unanswered_questions_count=count,
        unanswered_questions=question_samples,
    )
