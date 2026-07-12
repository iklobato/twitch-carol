"""EventSub notifications through the real signed endpoint, against the DB:
stream lifecycle, event recording, amount extraction and dedup."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from core.eventsub import (
    HEADER_MESSAGE_ID,
    HEADER_MESSAGE_TYPE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    compute_signature,
)
from core.models import Event, Stream, StreamStatus
from tests.factories import make_channel, make_stream
from tests.test_eventsub import SECRET

pytestmark = pytest.mark.usefixtures("fernet_key")


@pytest.fixture
def eventsub_env(monkeypatch: pytest.MonkeyPatch, twitch_env: None) -> None:
    from core.config import get_settings

    monkeypatch.setenv("TWITCH_EVENTSUB_SECRET", SECRET)
    get_settings.cache_clear()


def post_notification(client, sub_type: str, event: dict, message_id: str = "") -> int:
    body = json.dumps(
        {
            "subscription": {"id": "sub-1", "type": sub_type, "version": "1"},
            "event": event,
        }
    ).encode()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    message_id = message_id or f"msg-{sub_type}-{timestamp}-{hash(body)}"
    response = client.post(
        "/eventsub/callback",
        content=body,
        headers={
            HEADER_MESSAGE_ID: message_id,
            HEADER_TIMESTAMP: timestamp,
            HEADER_MESSAGE_TYPE: "notification",
            HEADER_SIGNATURE: compute_signature(SECRET, message_id, timestamp, body),
        },
    )
    return response.status_code


def test_stream_online_creates_stream_idempotently(
    api_client, db, eventsub_env
) -> None:
    channel = make_channel(db)
    event = {
        "broadcaster_user_id": str(channel.twitch_user_id),
        "type": "live",
        "started_at": datetime.now(UTC).isoformat(),
    }
    assert post_notification(api_client, "stream.online", event) == 204
    assert (
        post_notification(api_client, "stream.online", event, message_id="other-id")
        == 204
    )

    streams = db.scalars(select(Stream).where(Stream.channel_id == channel.id)).all()
    assert len(streams) == 1
    assert streams[0].status == StreamStatus.CAPTURING


def test_stream_offline_sets_ended_at_once(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.CAPTURING, duration_minutes=None)
    event = {"broadcaster_user_id": str(channel.twitch_user_id)}

    assert post_notification(api_client, "stream.offline", event) == 204
    db.refresh(stream)
    first_ended_at = stream.ended_at
    assert first_ended_at is not None
    assert stream.status == StreamStatus.CAPTURING  # worker finalizes, not the webhook

    assert (
        post_notification(api_client, "stream.offline", event, message_id="again")
        == 204
    )
    db.refresh(stream)
    assert stream.ended_at == first_ended_at


def test_events_recorded_with_amounts(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.CAPTURING, duration_minutes=None)
    base = {"broadcaster_user_id": str(channel.twitch_user_id)}

    assert post_notification(api_client, "channel.cheer", {**base, "bits": 500}) == 204
    assert (
        post_notification(api_client, "channel.subscribe", {**base, "tier": "2000"})
        == 204
    )
    assert (
        post_notification(
            api_client,
            "channel.raid",
            {"to_broadcaster_user_id": str(channel.twitch_user_id), "viewers": 42},
        )
        == 204
    )
    assert (
        post_notification(api_client, "channel.follow", {**base, "user_login": "fan"})
        == 204
    )

    events = {
        e.type: e for e in db.scalars(select(Event).where(Event.stream_id == stream.id))
    }
    assert events["channel.cheer"].amount == 500
    assert events["channel.subscribe"].amount == 2000
    assert events["channel.raid"].amount == 42
    assert events["channel.follow"].amount is None


def test_event_outside_active_stream_is_dropped(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)  # no active stream
    assert (
        post_notification(
            api_client,
            "channel.cheer",
            {"broadcaster_user_id": str(channel.twitch_user_id), "bits": 100},
        )
        == 204
    )
    assert db.scalars(select(Event).where(Event.channel_id == channel.id)).all() == []


def test_duplicate_message_id_is_processed_once(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    make_stream(db, channel, StreamStatus.CAPTURING, duration_minutes=None)
    event = {"broadcaster_user_id": str(channel.twitch_user_id), "bits": 77}

    assert (
        post_notification(api_client, "channel.cheer", event, message_id="dup-1") == 204
    )
    assert (
        post_notification(api_client, "channel.cheer", event, message_id="dup-1") == 204
    )

    events = db.scalars(select(Event).where(Event.channel_id == channel.id)).all()
    assert len(events) == 1


def test_unknown_channel_is_ignored_gracefully(api_client, db, eventsub_env) -> None:
    assert (
        post_notification(
            api_client,
            "stream.online",
            {
                "broadcaster_user_id": "424242424",
                "type": "live",
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
        == 204
    )


def test_channel_update_sets_title_and_records_event(
    api_client, db, eventsub_env
) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.CAPTURING, duration_minutes=None)
    assert (
        post_notification(
            api_client,
            "channel.update",
            {
                "broadcaster_user_id": str(channel.twitch_user_id),
                "title": "Título novo",
                "category_name": "Just Chatting",
            },
        )
        == 204
    )
    db.refresh(stream)
    assert stream.title == "Título novo"
    assert stream.category == "Just Chatting"
    recorded = db.scalars(select(Event).where(Event.stream_id == stream.id)).all()
    assert [e.type for e in recorded] == ["channel.update"]
