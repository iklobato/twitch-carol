"""Topic aggregation across a set of lives.

A topic Insight stores "name\ndescription", so the name is the first line and
grouping happens on that. Lives here rather than in the API layer so the SQL
stays reusable by code that cannot import from apps.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import methodcaller

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from core.models import Insight, InsightType, TranscriptSegment

TOPIC_WINDOW_PADDING = timedelta(seconds=60)


@dataclass(frozen=True)
class TopicWindow:
    """The stretch of one live a topic covers: from its first to its last
    cited speech segment, padded on both sides."""

    name: str
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def distance(self, moment: datetime) -> timedelta:
        if self.contains(moment):
            return timedelta(0)
        return max(self.start - moment, moment - self.end)


@dataclass(frozen=True)
class TopicTimeline:
    """Which topic a moment of a live (a cheer, a chat message) belongs to.
    Each live's windows are in rank order."""

    windows_by_stream: Mapping[int, tuple[TopicWindow, ...]]

    def topic_at(self, stream_id: int, moment: datetime) -> str | None:
        """The topic the moment falls in, else the nearest topic of the same
        live: a topic window covers about 1% of a live (measured on October
        2026 production data), so "inside only" credited 1.3% of the money.
        Inside two overlapping topics the higher-ranked wins, since min keeps
        the first of equal distances. None only for a live with no topic."""
        windows = self.windows_by_stream.get(stream_id, ())
        if not windows:
            return None
        return min(windows, key=methodcaller("distance", moment)).name

    def is_empty(self) -> bool:
        return not self.windows_by_stream


class TopicWindowReader:
    """Loads the topic windows of a set of lives from the speech segments
    each topic insight cites."""

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
        cited = [
            segments[segment_id]
            for segment_id in self._cited_ids(topic)
            if segment_id in segments
            and segments[segment_id].stream_id == topic.stream_id
        ]
        if not cited:
            return None
        return TopicWindow(
            name=topic.content.split("\n")[0],
            start=min(row.started_at for row in cited) - TOPIC_WINDOW_PADDING,
            end=max(row.ended_at for row in cited) + TOPIC_WINDOW_PADDING,
        )

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
