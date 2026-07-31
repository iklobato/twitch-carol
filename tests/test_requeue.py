"""Requeueing failed streams: restart at the step that failed, never twice."""

from sqlalchemy import select

from core.models import Job, JobStatus, StreamStatus
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE, requeue_failed_streams
from tests.factories import add_job, make_channel, make_stream


def _queued(db, stream_id: int, job_type: str) -> list[Job]:
    return list(
        db.scalars(
            select(Job)
            .where(Job.stream_id == stream_id)
            .where(Job.type == job_type)
            .where(Job.status == JobStatus.QUEUED)
        )
    )


def test_requeues_at_the_failed_step(db) -> None:
    channel = make_channel(db)
    broke_in_transcribe = make_stream(db, channel, StreamStatus.FAILED)
    add_job(db, broke_in_transcribe, JOB_TRANSCRIBE, JobStatus.FAILED)
    broke_in_analyze = make_stream(db, channel, StreamStatus.FAILED)
    add_job(db, broke_in_analyze, JOB_TRANSCRIBE, JobStatus.DONE)
    add_job(db, broke_in_analyze, JOB_ANALYZE, JobStatus.FAILED)

    requeued = requeue_failed_streams(db)

    assert sorted(requeued) == sorted(
        [
            (broke_in_transcribe.id, JOB_TRANSCRIBE),
            (broke_in_analyze.id, JOB_ANALYZE),
        ]
    )
    assert broke_in_transcribe.status is StreamStatus.QUEUED_TRANSCRIPTION
    assert broke_in_analyze.status is StreamStatus.QUEUED_ANALYSIS
    # the analyze one must not pay for transcription again
    assert _queued(db, broke_in_analyze.id, JOB_TRANSCRIBE) == []
    assert len(_queued(db, broke_in_analyze.id, JOB_ANALYZE)) == 1


def test_running_twice_does_not_queue_the_same_work_twice(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.FAILED)
    add_job(db, stream, JOB_TRANSCRIBE, JobStatus.FAILED)

    assert requeue_failed_streams(db) == [(stream.id, JOB_TRANSCRIBE)]
    stream.status = StreamStatus.FAILED  # as if it failed again mid-rerun

    assert requeue_failed_streams(db) == []
    assert len(_queued(db, stream.id, JOB_TRANSCRIBE)) == 1


def test_restricts_to_the_given_stream_ids(db) -> None:
    channel = make_channel(db)
    wanted = make_stream(db, channel, StreamStatus.FAILED)
    add_job(db, wanted, JOB_TRANSCRIBE, JobStatus.FAILED)
    other = make_stream(db, channel, StreamStatus.FAILED)
    add_job(db, other, JOB_TRANSCRIBE, JobStatus.FAILED)

    assert requeue_failed_streams(db, [wanted.id]) == [(wanted.id, JOB_TRANSCRIBE)]
    assert other.status is StreamStatus.FAILED
    assert _queued(db, other.id, JOB_TRANSCRIBE) == []


def test_skips_a_failed_stream_with_no_failed_job(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.FAILED)

    assert requeue_failed_streams(db) == []
    assert stream.status is StreamStatus.FAILED


def test_leaves_healthy_streams_alone(db) -> None:
    channel = make_channel(db)
    ready = make_stream(db, channel, StreamStatus.READY)
    add_job(db, ready, JOB_TRANSCRIBE, JobStatus.FAILED)  # an old failed attempt

    assert requeue_failed_streams(db) == []
    assert ready.status is StreamStatus.READY
