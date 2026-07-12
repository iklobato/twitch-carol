"""Programmatic evidence validation (product rule 1): an insight is only
stored if its cited message/segment ids really exist in this stream. Anything
unverifiable is discarded and logged, never shown."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ChatMessage, TranscriptSegment

logger = logging.getLogger(__name__)


def validated_evidence(
    db: Session,
    stream_id: int,
    candidate: dict[str, Any],
    allowed_message_ids: set[int],
    allowed_segment_ids: set[int],
) -> dict[str, Any] | None:
    """Returns the evidence dict with only verified references, or None when
    nothing verifiable remains (insight must then be discarded).

    A reference only counts when the model actually saw it in the prompt
    (allowed_*) AND it exists in this stream's tables: an id that merely
    happens to exist in the DB is a hallucinated citation, not evidence."""
    cited_messages = [
        i for i in _int_list(candidate.get("message_ids")) if i in allowed_message_ids
    ]
    cited_segments = [
        i for i in _int_list(candidate.get("segment_ids")) if i in allowed_segment_ids
    ]
    message_ids = _existing_message_ids(db, stream_id, cited_messages)
    segment_ids = _existing_segment_ids(db, stream_id, cited_segments)
    window = candidate.get("window")
    if not message_ids and not segment_ids:
        return None
    evidence: dict[str, Any] = {"message_ids": message_ids, "segment_ids": segment_ids}
    if isinstance(window, dict) and "start" in window and "end" in window:
        evidence["window"] = {"start": str(window["start"]), "end": str(window["end"])}
    return evidence


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _existing_message_ids(db: Session, stream_id: int, ids: list[int]) -> list[int]:
    if not ids:
        return []
    rows = db.scalars(
        select(ChatMessage.id)
        .where(ChatMessage.stream_id == stream_id)
        .where(ChatMessage.id.in_(ids))
    )
    return sorted(set(rows))


def _existing_segment_ids(db: Session, stream_id: int, ids: list[int]) -> list[int]:
    if not ids:
        return []
    rows = db.scalars(
        select(TranscriptSegment.id)
        .where(TranscriptSegment.stream_id == stream_id)
        .where(TranscriptSegment.id.in_(ids))
    )
    return sorted(set(rows))
