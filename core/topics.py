"""Topic aggregation across a set of lives.

A topic Insight stores "name\ndescription", so the name is the first line and
grouping happens on that. Lives here rather than in the API layer so the SQL
stays reusable by code that cannot import from apps.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import methodcaller

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from core.models import Insight, InsightType, TranscriptSegment

TOPIC_WINDOW_PADDING = timedelta(seconds=60)


@dataclass(frozen=True)
class TopicSpan:
    """One continuous stretch of a live."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def distance(self, moment: datetime) -> timedelta:
        if self.contains(moment):
            return timedelta(0)
        return max(self.start - moment, moment - self.end)

    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class TopicWindow:
    """The parts of one live a topic covers: the 15-minute analysis blocks
    the model gave it, or, for topics analyzed before blocks existed, its
    first to last cited speech segment padded on both sides."""

    insight_id: int
    name: str
    spans: tuple[TopicSpan, ...]

    @property
    def start(self) -> datetime:
        return min(span.start for span in self.spans)

    @property
    def end(self) -> datetime:
        return max(span.end for span in self.spans)

    def contains(self, moment: datetime) -> bool:
        return any(span.contains(moment) for span in self.spans)

    def distance(self, moment: datetime) -> timedelta:
        return min(span.distance(moment) for span in self.spans)

    def duration(self) -> timedelta:
        return sum((span.duration() for span in self.spans), timedelta(0))


@dataclass(frozen=True)
class TopicTimeline:
    """Which topic a moment of a live (a cheer, a chat message) belongs to.
    Each live's windows are in rank order."""

    windows_by_stream: Mapping[int, tuple[TopicWindow, ...]]

    def topic_at(self, stream_id: int, moment: datetime) -> str | None:
        """The topic the moment falls in, else the nearest topic of the same
        live: a topic from cited speech only covers about 1% of a live
        (measured on October 2026 production data), so "inside only"
        credited 1.3% of the money. Inside two overlapping topics the
        higher-ranked wins, since min keeps the first of equal distances.
        None only for a live with no topic."""
        windows = self.windows_of(stream_id)
        if not windows:
            return None
        return min(windows, key=methodcaller("distance", moment)).name

    def windows_of(self, stream_id: int) -> tuple[TopicWindow, ...]:
        return self.windows_by_stream.get(stream_id, ())

    def every_window(self) -> Iterator[TopicWindow]:
        for windows in self.windows_by_stream.values():
            yield from windows

    def window_for(self, insight_id: int) -> TopicWindow | None:
        return next(
            (window for window in self.every_window() if window.insight_id == insight_id),
            None,
        )

    def is_empty(self) -> bool:
        return not self.windows_by_stream


class TopicWindowReader:
    """Loads the topic windows of a set of lives from each topic insight's
    evidence: its blocks, else the speech segments it cites."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def timeline(self, stream_ids: list[int]) -> TopicTimeline:
        topics = self._topics(stream_ids)
        segments = self._cited_segment_rows(topics)
        windows: dict[int, list[TopicWindow]] = defaultdict(list)
        for topic in topics:
            window = self._window(topic, segments)
            if window is not None:
                windows[topic.stream_id].append(window)
        return TopicTimeline(
            {stream_id: tuple(found) for stream_id, found in windows.items()}
        )

    def _topics(self, stream_ids: list[int]) -> list[Insight]:
        if not stream_ids:
            return []
        # Stored in rank order (workers.analyze.pipeline._store_topics), so
        # id order is rank order.
        return list(
            self._db.scalars(
                select(Insight)
                .where(Insight.stream_id.in_(stream_ids))
                .where(Insight.type == InsightType.TOPIC)
                .order_by(Insight.id)
            )
        )

    def _cited_segment_rows(self, topics: list[Insight]) -> dict[int, Row]:
        segment_ids = {
            segment_id for topic in topics for segment_id in self._cited_ids(topic)
        }
        if not segment_ids:
            return {}
        rows = self._db.execute(
            select(
                TranscriptSegment.id,
                TranscriptSegment.stream_id,
                TranscriptSegment.started_at,
                TranscriptSegment.ended_at,
            ).where(TranscriptSegment.id.in_(segment_ids))
        )
        return {row.id: row for row in rows}

    def _window(self, topic: Insight, segments: dict[int, Row]) -> TopicWindow | None:
        spans = self._block_spans(topic) or self._segment_span(topic, segments)
        if not spans:
            return None
        return TopicWindow(
            insight_id=topic.id, name=topic.content.split("\n")[0], spans=spans
        )

    def _block_spans(self, topic: Insight) -> tuple[TopicSpan, ...]:
        blocks = topic.evidence.get("blocks", [])
        if not isinstance(blocks, list):
            return ()
        return tuple(
            TopicSpan(
                datetime.fromisoformat(block["start"]),
                datetime.fromisoformat(block["end"]),
            )
            for block in blocks
            if isinstance(block, dict) and "start" in block and "end" in block
        )

    def _segment_span(
        self, topic: Insight, segments: dict[int, Row]
    ) -> tuple[TopicSpan, ...]:
        cited = [
            segments[segment_id]
            for segment_id in self._cited_ids(topic)
            if segment_id in segments
            and segments[segment_id].stream_id == topic.stream_id
        ]
        if not cited:
            return ()
        start = min(row.started_at for row in cited) - TOPIC_WINDOW_PADDING
        end = max(row.ended_at for row in cited) + TOPIC_WINDOW_PADDING
        return (TopicSpan(start, end),)

    def _cited_ids(self, topic: Insight) -> list[int]:
        cited = topic.evidence.get("segment_ids", [])
        if not isinstance(cited, list):
            return []
        return [int(segment_id) for segment_id in cited]


def recurring_topics(
    db: Session, stream_ids: list[int], limit: int
) -> list[tuple[str, int]]:
    """(topic name, how many of these lives talked about it), most recurrent
    first. Ranks by reach across lives, not by how loud the chat got."""
    if not stream_ids:
        return []
    name = func.split_part(Insight.content, "\n", 1)
    lives = func.count(func.distinct(Insight.stream_id))
    rows = db.execute(
        select(name, lives)
        .where(Insight.stream_id.in_(stream_ids))
        .where(Insight.type == InsightType.TOPIC)
        .group_by(name)
        .order_by(lives.desc())
        .limit(limit)
    ).all()
    return [(row[0], row[1]) for row in rows]
