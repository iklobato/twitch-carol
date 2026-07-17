"""All-time record tracking: per-live metrics, record-breaking history, current
holder lookup, and the backfill over existing lives."""

import pytest
from sqlalchemy import select

from core.finance import CHEER, GIFT, SUBSCRIBE
from core.models import StreamRecord
from core.records import (
    RecordMetric,
    add_record_facts,
    backfill_records,
    compute_stream_metrics,
    records_held_by_stream,
    update_stream_records,
)
from tests.factories import (
    add_chat,
    add_event,
    add_viewer_samples,
    make_channel,
    make_stream,
)

pytestmark = pytest.mark.usefixtures("fernet_key", "twitch_env")


def test_compute_stream_metrics_covers_all_metrics(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    add_chat(db, stream, count=10, author="ana")
    add_chat(db, stream, count=5, author="bob")
    add_event(db, stream, event_type="channel.follow")
    add_event(db, stream, event_type=SUBSCRIBE, amount=1000)
    add_event(db, stream, event_type=CHEER, amount=200)
    add_event(db, stream, event_type=GIFT, amount=3, payload={"tier": 1000})
    add_viewer_samples(db, stream, [10, 40, 25])

    metrics = compute_stream_metrics(db, stream)

    assert set(metrics) == set(RecordMetric)  # all 14 present
    assert metrics[RecordMetric.MESSAGES] == 15
    assert metrics[RecordMetric.CHATTERS] == 2
    assert metrics[RecordMetric.FOLLOWS] == 1
    assert metrics[RecordMetric.SUBS] == 1
    assert metrics[RecordMetric.BITS] == 200
    assert metrics[RecordMetric.GIFTS] == 3
    assert metrics[RecordMetric.PEAK_VIEWERS] == 40
    assert metrics[RecordMetric.DURATION_MINUTES] == 30
    assert metrics[RecordMetric.MESSAGES_PER_MIN] == 0.5


def test_new_live_beating_prior_best_sets_record(db) -> None:
    channel = make_channel(db)
    first = make_stream(db, channel, started_minutes_ago=200)
    add_chat(db, first, count=5)
    update_stream_records(db, first)

    second = make_stream(db, channel, started_minutes_ago=100)
    add_chat(db, second, count=20)
    broke = update_stream_records(db, second)

    assert RecordMetric.MESSAGES in broke
    held = records_held_by_stream(db, channel.id)
    assert "mensagens no chat" in held[second.id]
    # first lost the chat record to the bigger live (equal-duration record it keeps)
    assert "mensagens no chat" not in held.get(first.id, [])


def test_lower_live_does_not_steal_the_record(db) -> None:
    channel = make_channel(db)
    big = make_stream(db, channel, started_minutes_ago=200)
    add_chat(db, big, count=30)
    update_stream_records(db, big)

    small = make_stream(db, channel, started_minutes_ago=100)
    add_chat(db, small, count=3)
    broke = update_stream_records(db, small)

    assert RecordMetric.MESSAGES not in broke
    held = records_held_by_stream(db, channel.id)
    assert "mensagens no chat" in held[big.id]
    assert small.id not in held


def test_reanalysis_is_idempotent(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, count=12)

    update_stream_records(db, stream)
    update_stream_records(db, stream)  # re-analysis

    rows = db.scalars(
        select(StreamRecord).where(
            StreamRecord.channel_id == channel.id,
            StreamRecord.metric == RecordMetric.MESSAGES.value,
        )
    ).all()
    assert len(rows) == 1  # no duplicate record row


def test_backfill_orders_by_time_so_only_the_best_holds(db) -> None:
    channel = make_channel(db)
    older = make_stream(db, channel, started_minutes_ago=300)
    add_chat(db, older, count=8)
    newer = make_stream(db, channel, started_minutes_ago=100)
    add_chat(db, newer, count=25)

    written = backfill_records(db, channel.id)

    # older sets the first record, newer beats messages/chatters/rate -> both rows exist
    assert written > 0
    held = records_held_by_stream(db, channel.id)
    assert "mensagens no chat" in held[newer.id]
    assert "mensagens no chat" not in held.get(older.id, [])


def test_add_record_facts_lists_marks_and_fresh_break(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_chat(db, stream, count=9)
    broke = update_stream_records(db, stream)

    facts: list[str] = []
    add_record_facts(db, channel.id, broke, facts)

    assert any("Melhores marcas do canal" in fact for fact in facts)
    assert any("bateu o recorde" in fact for fact in facts)
    assert facts[0].startswith("[1]")
