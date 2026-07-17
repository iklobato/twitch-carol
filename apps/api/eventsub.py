"""EventSub webhook endpoint. The simulator posts here too, signed with the
same secret, so simulation exercises this exact path."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.deps import DbSession
from core.config import get_settings
from core.eventsub import (
    HEADER_MESSAGE_ID,
    HEADER_MESSAGE_TYPE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MESSAGE_TYPE_NOTIFICATION,
    MESSAGE_TYPE_REVOCATION,
    MESSAGE_TYPE_VERIFICATION,
    claim_message,
    timestamp_is_fresh,
    verify_signature,
)
from core.models import Channel, Event, Follower
from core.streams import get_active_stream, mark_stream_offline, start_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eventsub")


@router.post("/callback")
async def eventsub_callback(
    request: Request, db: DbSession
) -> Response:
    secret = get_settings().twitch_eventsub_secret
    if not secret:
        raise HTTPException(
            status_code=503, detail="TWITCH_EVENTSUB_SECRET is not configured"
        )

    body = await request.body()
    message_id = request.headers.get(HEADER_MESSAGE_ID, "")
    timestamp = request.headers.get(HEADER_TIMESTAMP, "")
    signature = request.headers.get(HEADER_SIGNATURE, "")
    if not verify_signature(secret, message_id, timestamp, signature, body):
        raise HTTPException(status_code=403, detail="Invalid EventSub signature")
    if not timestamp_is_fresh(timestamp):
        raise HTTPException(status_code=403, detail="Stale EventSub message")

    payload = json.loads(body)
    message_type = request.headers.get(HEADER_MESSAGE_TYPE, "")

    if message_type == MESSAGE_TYPE_VERIFICATION:
        return PlainTextResponse(payload["challenge"])
    if message_type == MESSAGE_TYPE_REVOCATION:
        logger.warning(
            "eventsub subscription revoked",
            extra={"event_type": payload["subscription"]["type"]},
        )
        return Response(status_code=204)
    if message_type != MESSAGE_TYPE_NOTIFICATION:
        raise HTTPException(
            status_code=400, detail=f"Unknown message type: {message_type}"
        )

    if not claim_message(db, message_id):
        return Response(status_code=204)

    occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    _handle_notification(db, payload, occurred_at)
    db.commit()
    return Response(status_code=204)


def _handle_notification(db: Session, payload: dict, occurred_at: datetime) -> None:
    event_type = payload["subscription"]["type"]
    event = payload["event"]
    channel = _find_channel(db, event)
    if channel is None:
        logger.warning(
            "eventsub notification for unknown channel",
            extra={"event_type": event_type},
        )
        return
    handler = NOTIFICATION_HANDLERS.get(event_type, _record_event)
    handler(db, channel, event_type, event, occurred_at)


def _find_channel(db: Session, event: dict) -> Channel | None:
    raw_id = event.get("broadcaster_user_id") or event.get("to_broadcaster_user_id")
    if raw_id is None:
        return None
    return db.scalar(select(Channel).where(Channel.twitch_user_id == int(raw_id)))


def _handle_online(
    db: Session, channel: Channel, event_type: str, event: dict, occurred_at: datetime
) -> None:
    started_at = datetime.fromisoformat(event["started_at"].replace("Z", "+00:00"))
    start_stream(db, channel, started_at)


def _handle_offline(
    db: Session, channel: Channel, event_type: str, event: dict, occurred_at: datetime
) -> None:
    stream = get_active_stream(db, channel.id)
    if stream is None:
        logger.warning(
            "stream.offline without active stream", extra={"channel_id": channel.id}
        )
        return
    mark_stream_offline(db, stream, datetime.now(UTC))


def _handle_channel_update(
    db: Session, channel: Channel, event_type: str, event: dict, occurred_at: datetime
) -> None:
    stream = get_active_stream(db, channel.id)
    if stream is not None:
        stream.title = event.get("title")
        stream.category = event.get("category_name")
    _record_event(db, channel, event_type, event, occurred_at)


def _amount_from_field(field: str) -> Callable[[dict], int | None]:
    def extract(event: dict) -> int | None:
        value = event.get(field)
        return int(value) if value is not None else None

    return extract


AMOUNT_EXTRACTORS: dict[str, Callable[[dict], int | None]] = {
    "channel.cheer": _amount_from_field("bits"),
    "channel.raid": _amount_from_field("viewers"),
    "channel.subscribe": _amount_from_field("tier"),
    "channel.subscription.message": _amount_from_field("tier"),
    "channel.subscription.gift": _amount_from_field("total"),
    "channel.subscription.end": _amount_from_field("tier"),
    "channel.hype_train.end": _amount_from_field("total"),
    "channel.ad_break.begin": _amount_from_field("duration_seconds"),
}


def _record_event(
    db: Session, channel: Channel, event_type: str, event: dict, occurred_at: datetime
) -> None:
    stream = get_active_stream(db, channel.id)
    if stream is None:
        # v1 keeps only the live timeline; off-stream events are dropped.
        logger.info(
            "event outside an active stream dropped",
            extra={"channel_id": channel.id, "event_type": event_type},
        )
        return
    extract_amount = AMOUNT_EXTRACTORS.get(event_type, _no_amount)
    db.add(
        Event(
            stream_id=stream.id,
            channel_id=channel.id,
            occurred_at=occurred_at,
            type=event_type,
            payload=event,
            amount=extract_amount(event),
        )
    )
    logger.info(
        "event recorded",
        extra={
            "stream_id": stream.id,
            "channel_id": channel.id,
            "event_type": event_type,
        },
    )


def _no_amount(event: dict) -> int | None:
    return None


def _handle_follow(
    db: Session, channel: Channel, event_type: str, event: dict, occurred_at: datetime
) -> None:
    _upsert_follower(db, channel, event, occurred_at)
    # keep the per-stream follow event too: growth counts follows per stream
    _record_event(db, channel, event_type, event, occurred_at)


def _upsert_follower(
    db: Session, channel: Channel, event: dict, occurred_at: datetime
) -> None:
    user_id = int(event["user_id"])
    already_following = db.scalar(
        select(Follower.id).where(
            Follower.channel_id == channel.id,
            Follower.twitch_user_id == user_id,
        )
    )
    if already_following is not None:
        return
    raw_followed_at = event.get("followed_at")
    followed_at = (
        datetime.fromisoformat(raw_followed_at.replace("Z", "+00:00"))
        if raw_followed_at
        else occurred_at
    )
    db.add(
        Follower(
            channel_id=channel.id,
            twitch_user_id=user_id,
            login=event["user_login"],
            followed_at=followed_at,
        )
    )


NOTIFICATION_HANDLERS: dict[
    str, Callable[[Session, Channel, str, dict, datetime], None]
] = {
    "stream.online": _handle_online,
    "stream.offline": _handle_offline,
    "channel.update": _handle_channel_update,
    "channel.follow": _handle_follow,
}
