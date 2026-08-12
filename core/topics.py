"""Topic aggregation across a set of lives.

A topic Insight stores "name\ndescription", so the name is the first line and
grouping happens on that. Lives here rather than in the API layer so the SQL
stays reusable by code that cannot import from apps.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Insight, InsightType


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
