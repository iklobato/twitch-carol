"""Dashboard API: lives, report, timeline, peak drill-down, insight feedback,
full-text search and queue status. All numbers come from core.metrics (SQL)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.deps import CurrentChannel, DbSession
from core.metrics import (
    average_job_seconds,
    chat_rate_buckets,
    previous_streams_average,
    stream_numbers,
)
from core.models import (
    Channel,
    ChatMessage,
    Event,
    Insight,
    InsightFeedback,
    InsightType,
    Job,
    JobStatus,
    Peak,
    Stream,
    TranscriptSegment,
    ViewerSample,
)
from core.schedule import HISTORY_LIMIT, estimate_next_live

router = APIRouter(prefix="/api")

PEAK_CHAT_LIMIT = 200
SEARCH_LIMIT = 25


def _owned_stream(db: Session, channel: Channel, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None or stream.channel_id != channel.id:
        raise HTTPException(status_code=404, detail="Stream not found")
    return stream


class StreamListItem(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None
    title: str | None
    category: str | None
    status: str
    messages: int
    chatters: int
    events: int
    followers: int
    peak_viewers: int


FOLLOW_EVENT_TYPE = "channel.follow"


@router.get("/streams")
def list_streams(channel: CurrentChannel, db: DbSession) -> list[StreamListItem]:
    chat_stats: dict[int, tuple[int, int]] = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(
                ChatMessage.stream_id,
                func.count(),
                func.count(func.distinct(ChatMessage.author_id)),
            )
            .where(ChatMessage.channel_id == channel.id)
            .group_by(ChatMessage.stream_id)
        )
    }
    event_stats: dict[int, tuple[int, int]] = {
        row[0]: (row[1], row[2])
        for row in db.execute(
            select(
                Event.stream_id,
                func.count(),
                func.count().filter(Event.type == FOLLOW_EVENT_TYPE),
            )
            .where(Event.channel_id == channel.id)
            .group_by(Event.stream_id)
        )
    }
    viewer_peaks: dict[int, int] = {
        row[0]: row[1]
        for row in db.execute(
            select(ViewerSample.stream_id, func.max(ViewerSample.viewer_count))
            .join(Stream, ViewerSample.stream_id == Stream.id)
            .where(Stream.channel_id == channel.id)
            .group_by(ViewerSample.stream_id)
        )
    }
    streams = db.scalars(
        select(Stream)
        .where(Stream.channel_id == channel.id)
        .order_by(Stream.started_at.desc())
    ).all()
    return [
        StreamListItem(
            id=s.id,
            started_at=s.started_at,
            ended_at=s.ended_at,
            title=s.title,
            category=s.category,
            status=s.status.value,
            messages=chat_stats.get(s.id, (0, 0))[0],
            chatters=chat_stats.get(s.id, (0, 0))[1],
            events=event_stats.get(s.id, (0, 0))[0],
            followers=event_stats.get(s.id, (0, 0))[1],
            peak_viewers=viewer_peaks.get(s.id, 0),
        )
        for s in streams
    ]


class NumberComparison(BaseModel):
    value: float
    previous_avg: float | None
    delta_pct: float | None


class PeakOut(BaseModel):
    id: int
    window_start: datetime
    window_end: datetime
    metric: str
    score: float


class CitedMessage(BaseModel):
    id: int
    sent_at: datetime
    author_login: str
    text: str


class CitedSegment(BaseModel):
    id: int
    started_at: datetime
    text: str | None


class InsightOut(BaseModel):
    id: int
    type: str
    content: str
    evidence: dict
    feedback: str | None
    cited_messages: list[CitedMessage]
    cited_segments: list[CitedSegment]
    # topic engagement: SQL chat rate in the topic's cited window relative to
    # the busiest topic (0-100); None for non-topic insights
    engagement_pct: float | None


class StreamReport(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime | None
    title: str | None
    category: str | None
    status: str
    audit: dict | None
    numbers: dict[str, NumberComparison]
    peaks: list[PeakOut]
    insights: list[InsightOut]


def _compare(
    current: dict[str, float], previous: dict[str, float] | None
) -> dict[str, NumberComparison]:
    result = {}
    for key, value in current.items():
        previous_avg = previous.get(key) if previous else None
        delta = None
        if previous_avg is not None and previous_avg > 0:
            delta = round((value - previous_avg) / previous_avg * 100, 1)
        result[key] = NumberComparison(
            value=value, previous_avg=previous_avg, delta_pct=delta
        )
    return result


@router.get("/streams/{stream_id}")
def stream_report(
    stream_id: int, channel: CurrentChannel, db: DbSession
) -> StreamReport:
    stream = _owned_stream(db, channel, stream_id)
    peaks = db.scalars(
        select(Peak).where(Peak.stream_id == stream.id).order_by(Peak.score.desc())
    ).all()
    insights = db.scalars(
        select(Insight).where(Insight.stream_id == stream.id).order_by(Insight.id)
    ).all()
    messages_by_id, segments_by_id = _resolve_citations(db, stream.id, insights)
    engagement = _topic_engagement(db, stream.id, insights, segments_by_id)
    return StreamReport(
        id=stream.id,
        started_at=stream.started_at,
        ended_at=stream.ended_at,
        title=stream.title,
        category=stream.category,
        status=stream.status.value,
        audit=stream.audit,
        numbers=_compare(
            stream_numbers(db, stream), previous_streams_average(db, stream)
        ),
        peaks=[
            PeakOut(
                id=p.id,
                window_start=p.window_start,
                window_end=p.window_end,
                metric=p.metric,
                score=p.score,
            )
            for p in peaks
        ],
        insights=[
            _insight_out(i, messages_by_id, segments_by_id, engagement.get(i.id))
            for i in insights
        ],
    )


def _cited_ids(insight: Insight, key: str) -> list[int]:
    value = insight.evidence.get(key, [])
    return [int(i) for i in value] if isinstance(value, list) else []


def _resolve_citations(
    db: Session, stream_id: int, insights: Sequence[Insight]
) -> tuple[dict[int, ChatMessage], dict[int, TranscriptSegment]]:
    """Cited ids -> rows, fetched once for the whole report so evidence is
    clickable in the UI without extra requests."""
    message_ids = {
        i for insight in insights for i in _cited_ids(insight, "message_ids")
    }
    segment_ids = {
        i for insight in insights for i in _cited_ids(insight, "segment_ids")
    }
    messages = (
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.stream_id == stream_id)
            .where(ChatMessage.id.in_(message_ids))
        ).all()
        if message_ids
        else []
    )
    segments = (
        db.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.stream_id == stream_id)
            .where(TranscriptSegment.id.in_(segment_ids))
        ).all()
        if segment_ids
        else []
    )
    return {m.id: m for m in messages}, {s.id: s for s in segments}


def _topic_engagement(
    db: Session,
    stream_id: int,
    insights: Sequence[Insight],
    segments_by_id: dict[int, TranscriptSegment],
) -> dict[int, float]:
    """Chat rate (SQL buckets) inside each topic's cited window, normalized to
    the busiest topic = 100. Never derived from LLM text (rule 2)."""
    topics = [i for i in insights if i.type == InsightType.TOPIC]
    if not topics:
        return {}
    buckets = chat_rate_buckets(db, stream_id)
    if not buckets:
        return {}

    def window_rate(insight: Insight) -> float:
        cited = [
            segments_by_id[i]
            for i in _cited_ids(insight, "segment_ids")
            if i in segments_by_id
        ]
        if not cited:
            return 0.0
        start = min(s.started_at for s in cited) - timedelta(seconds=60)
        end = max(s.ended_at for s in cited) + timedelta(seconds=60)
        rates = [count for t, count in buckets if start <= t <= end]
        return sum(rates) / len(rates) if rates else 0.0

    rates = {insight.id: window_rate(insight) for insight in topics}
    busiest = max(rates.values())
    if busiest <= 0:
        return {insight_id: 0.0 for insight_id in rates}
    return {
        insight_id: round(rate / busiest * 100, 1) for insight_id, rate in rates.items()
    }


def _insight_out(
    insight: Insight,
    messages_by_id: dict[int, ChatMessage],
    segments_by_id: dict[int, TranscriptSegment],
    engagement_pct: float | None,
) -> InsightOut:
    return InsightOut(
        id=insight.id,
        type=insight.type.value,
        content=insight.content,
        evidence=insight.evidence,
        feedback=insight.feedback.value if insight.feedback else None,
        cited_messages=[
            CitedMessage(
                id=m.id, sent_at=m.sent_at, author_login=m.author_login, text=m.text
            )
            for i in _cited_ids(insight, "message_ids")
            if (m := messages_by_id.get(i)) is not None
        ],
        cited_segments=[
            CitedSegment(id=s.id, started_at=s.started_at, text=s.text)
            for i in _cited_ids(insight, "segment_ids")
            if (s := segments_by_id.get(i)) is not None
        ],
        engagement_pct=engagement_pct,
    )


class TimelinePoint(BaseModel):
    t: datetime
    value: float


class EventMarker(BaseModel):
    t: datetime
    type: str
    amount: int | None


class Timeline(BaseModel):
    chat: list[TimelinePoint]
    viewers: list[TimelinePoint]
    events: list[EventMarker]
    peaks: list[PeakOut]


@router.get("/streams/{stream_id}/timeline")
def stream_timeline(stream_id: int, channel: CurrentChannel, db: DbSession) -> Timeline:
    stream = _owned_stream(db, channel, stream_id)
    viewers = db.execute(
        select(ViewerSample.sampled_at, ViewerSample.viewer_count)
        .where(ViewerSample.stream_id == stream.id)
        .order_by(ViewerSample.sampled_at)
    ).all()
    events = db.scalars(
        select(Event).where(Event.stream_id == stream.id).order_by(Event.occurred_at)
    ).all()
    peaks = db.scalars(select(Peak).where(Peak.stream_id == stream.id)).all()
    return Timeline(
        chat=[
            TimelinePoint(t=t, value=count)
            for t, count in chat_rate_buckets(db, stream.id)
        ],
        viewers=[TimelinePoint(t=t, value=count) for t, count in viewers],
        events=[
            EventMarker(t=e.occurred_at, type=e.type, amount=e.amount) for e in events
        ],
        peaks=[
            PeakOut(
                id=p.id,
                window_start=p.window_start,
                window_end=p.window_end,
                metric=p.metric,
                score=p.score,
            )
            for p in peaks
        ],
    )


class PeakChatMessage(BaseModel):
    id: int
    sent_at: datetime
    author_login: str
    text: str


class PeakSegment(BaseModel):
    id: int
    started_at: datetime
    ended_at: datetime
    kind: str
    text: str | None


class PeakDetail(BaseModel):
    peak: PeakOut
    segments: list[PeakSegment]
    messages: list[PeakChatMessage]


@router.get("/streams/{stream_id}/peaks/{peak_id}")
def peak_detail(
    stream_id: int, peak_id: int, channel: CurrentChannel, db: DbSession
) -> PeakDetail:
    stream = _owned_stream(db, channel, stream_id)
    peak = db.get(Peak, peak_id)
    if peak is None or peak.stream_id != stream.id:
        raise HTTPException(status_code=404, detail="Peak not found")
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.stream_id == stream.id)
        .where(TranscriptSegment.started_at < peak.window_end)
        .where(TranscriptSegment.ended_at > peak.window_start)
        .order_by(TranscriptSegment.started_at)
    ).all()
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.stream_id == stream.id)
        .where(ChatMessage.sent_at >= peak.window_start)
        .where(ChatMessage.sent_at < peak.window_end)
        .order_by(ChatMessage.sent_at)
        .limit(PEAK_CHAT_LIMIT)
    ).all()
    return PeakDetail(
        peak=PeakOut(
            id=peak.id,
            window_start=peak.window_start,
            window_end=peak.window_end,
            metric=peak.metric,
            score=peak.score,
        ),
        segments=[
            PeakSegment(
                id=s.id,
                started_at=s.started_at,
                ended_at=s.ended_at,
                kind=s.kind.value,
                text=s.text,
            )
            for s in segments
        ],
        messages=[
            PeakChatMessage(
                id=m.id, sent_at=m.sent_at, author_login=m.author_login, text=m.text
            )
            for m in messages
        ],
    )


class FeedbackIn(BaseModel):
    feedback: Literal["useful", "not_useful"] | None


@router.post("/insights/{insight_id}/feedback", status_code=204)
def insight_feedback(
    insight_id: int, body: FeedbackIn, channel: CurrentChannel, db: DbSession
) -> None:
    insight = db.get(Insight, insight_id)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    _owned_stream(db, channel, insight.stream_id)
    insight.feedback = InsightFeedback(body.feedback) if body.feedback else None
    db.commit()


class SearchHit(BaseModel):
    stream_id: int
    source: Literal["chat", "transcript"]
    at: datetime
    text: str
    author_login: str | None = None


@router.get("/search")
def search(
    channel: CurrentChannel,
    db: DbSession,
    q: str = Query(min_length=2),
    stream_id: int | None = None,
) -> list[SearchHit]:
    ts_query = func.websearch_to_tsquery("portuguese", q)

    chat_query = (
        select(ChatMessage)
        .where(ChatMessage.channel_id == channel.id)
        .where(ChatMessage.text_search.op("@@")(ts_query))
        .order_by(ChatMessage.sent_at.desc())
        .limit(SEARCH_LIMIT)
    )
    transcript_query = (
        select(TranscriptSegment)
        .join(Stream, TranscriptSegment.stream_id == Stream.id)
        .where(Stream.channel_id == channel.id)
        .where(TranscriptSegment.text_search.op("@@")(ts_query))
        .order_by(TranscriptSegment.started_at.desc())
        .limit(SEARCH_LIMIT)
    )
    if stream_id is not None:
        chat_query = chat_query.where(ChatMessage.stream_id == stream_id)
        transcript_query = transcript_query.where(
            TranscriptSegment.stream_id == stream_id
        )

    hits = [
        SearchHit(
            stream_id=m.stream_id,
            source="chat",
            at=m.sent_at,
            text=m.text,
            author_login=m.author_login,
        )
        for m in db.scalars(chat_query)
    ]
    hits.extend(
        SearchHit(
            stream_id=s.stream_id,
            source="transcript",
            at=s.started_at,
            text=s.text or "",
        )
        for s in db.scalars(transcript_query)
    )
    return sorted(hits, key=lambda hit: hit.at, reverse=True)[:SEARCH_LIMIT]


class QueueItem(BaseModel):
    stream_id: int
    job_type: str
    status: str
    position: int | None
    jobs_ahead: int | None
    eta_seconds: float | None


@router.get("/queue")
def queue_status(channel: CurrentChannel, db: DbSession) -> list[QueueItem]:
    rows = db.execute(
        select(Job, Stream, Channel)
        .join(Stream, Job.stream_id == Stream.id)
        .join(Channel, Stream.channel_id == Channel.id)
        .where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
    ).all()
    now = datetime.now(UTC)
    deadlines: dict[int, datetime] = {}
    for _, _, job_channel in rows:
        if job_channel.id not in deadlines:
            history = list(
                db.scalars(
                    select(Stream.started_at)
                    .where(Stream.channel_id == job_channel.id)
                    .order_by(Stream.started_at.desc())
                    .limit(HISTORY_LIMIT)
                )
            )
            deadlines[job_channel.id] = estimate_next_live(now, history)

    items = []
    for job, stream, job_channel in rows:
        if job_channel.id != channel.id:
            continue
        position = None
        jobs_ahead = None
        eta = None
        if job.status == JobStatus.QUEUED:
            same_type_queued = [
                (j, c)
                for j, _, c in rows
                if j.type == job.type and j.status == JobStatus.QUEUED
            ]
            jobs_ahead = sum(
                1
                for j, c in same_type_queued
                if deadlines[c.id] < deadlines[job_channel.id]
            )
            position = jobs_ahead + 1
            avg_seconds = average_job_seconds(db, job.type)
            if avg_seconds is not None:
                eta = round((jobs_ahead + 1) * avg_seconds)
        items.append(
            QueueItem(
                stream_id=stream.id,
                job_type=job.type,
                status=job.status.value,
                position=position,
                jobs_ahead=jobs_ahead,
                eta_seconds=eta,
            )
        )
    return items
