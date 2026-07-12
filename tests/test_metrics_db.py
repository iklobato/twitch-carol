"""SQL metrics against the DB (product rule 2: UI numbers come from here)."""

from core.metrics import (
    average_job_seconds,
    chat_rate_buckets,
    previous_streams_average,
    stream_numbers,
)
from core.models import JobStatus, StreamStatus
from core.queues import JOB_TRANSCRIBE
from tests.factories import (
    add_chat,
    add_event,
    add_job,
    add_viewer_samples,
    make_channel,
    make_stream,
)


def test_stream_numbers(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=30)
    add_chat(db, stream, 10, author="a")
    add_chat(db, stream, 5, author="b", offset_seconds=100)
    add_event(db, stream, "channel.cheer", amount=100)
    add_viewer_samples(db, stream, [10, 30, 20])

    numbers = stream_numbers(db, stream)
    assert numbers["duration_minutes"] == 30.0
    assert numbers["messages"] == 15.0
    assert numbers["chatters"] == 2.0
    assert numbers["peak_viewers"] == 30.0
    assert numbers["avg_viewers"] == 20.0
    assert numbers["events"] == 1.0


def test_stream_numbers_empty_stream_is_all_zero(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, duration_minutes=10)
    numbers = stream_numbers(db, stream)
    assert numbers["messages"] == 0.0
    assert numbers["chatters"] == 0.0
    assert numbers["peak_viewers"] == 0.0
    assert numbers["events"] == 0.0


def test_previous_streams_average_only_ready_and_older(db) -> None:
    channel = make_channel(db)
    older_a = make_stream(db, channel, started_minutes_ago=3000)
    add_chat(db, older_a, 10)
    older_b = make_stream(db, channel, started_minutes_ago=2000)
    add_chat(db, older_b, 20)
    # failed stream must not enter the comparison
    make_stream(db, channel, StreamStatus.FAILED, started_minutes_ago=1500)
    current = make_stream(db, channel, started_minutes_ago=60)

    average = previous_streams_average(db, current)
    assert average is not None
    assert average["messages"] == 15.0


def test_previous_streams_average_none_without_history(db) -> None:
    channel = make_channel(db)
    current = make_stream(db, channel)
    assert previous_streams_average(db, current) is None


def test_chat_rate_buckets_only_this_stream(db) -> None:
    channel = make_channel(db)
    mine = make_stream(db, channel)
    other = make_stream(db, channel, started_minutes_ago=500)
    add_chat(db, mine, 6, spread_seconds=30)
    add_chat(db, other, 99, spread_seconds=30)

    buckets = chat_rate_buckets(db, mine.id)
    assert sum(count for _, count in buckets) == 6


def test_average_job_seconds_from_finished_jobs(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    add_job(
        db,
        stream,
        JOB_TRANSCRIBE,
        JobStatus.DONE,
        started_minutes_ago=20,
        finished_minutes_ago=10,
    )
    add_job(
        db,
        stream,
        JOB_TRANSCRIBE,
        JobStatus.DONE,
        started_minutes_ago=30,
        finished_minutes_ago=10,
    )

    average = average_job_seconds(db, JOB_TRANSCRIBE)
    assert average == ((10 * 60) + (20 * 60)) / 2


def test_average_job_seconds_none_without_history(db) -> None:
    assert average_job_seconds(db, JOB_TRANSCRIBE) is None
