"""A job whose worker died mid-run must come back.

Regression for the orphan bug: _queued_jobs only looks at QUEUED, so a job left
RUNNING by a dead worker (crash, OOM, redeploy) was never picked up again and
its stream sat in transcribing/analyzing forever.

The signal is the heartbeat, not elapsed time: a transcribe legitimately runs
90+ min, so a duration timeout would have to guess that ceiling and would kill
real work whenever it guessed low."""

from datetime import UTC, datetime, timedelta

from core.models import JobStatus, StreamStatus
from core.queues import JOB_TRANSCRIBE
from core.worker_loop import HEARTBEAT_STALE_AFTER, MAX_ATTEMPTS, reclaim_dead_jobs
from tests.factories import add_job, make_channel, make_stream

NOW = datetime.now(UTC)
DEAD = NOW - HEARTBEAT_STALE_AFTER - timedelta(minutes=1)


def _running_job(db, *, heartbeat, attempts=1, started_minutes_ago=120):
    channel = make_channel(db)
    stream = make_stream(db, channel)
    job = add_job(
        db,
        stream,
        JOB_TRANSCRIBE,
        JobStatus.RUNNING,
        started_minutes_ago=started_minutes_ago,
    )
    job.attempts = attempts
    job.last_heartbeat = heartbeat
    stream.status = StreamStatus.TRANSCRIBING
    db.flush()
    return job, stream


def test_requeues_job_whose_heartbeat_stopped(db) -> None:
    job, _ = _running_job(db, heartbeat=DEAD)

    reclaimed = reclaim_dead_jobs(db, JOB_TRANSCRIBE, NOW)

    assert [j.id for j in reclaimed] == [job.id]
    assert job.status == JobStatus.QUEUED
    assert "heartbeat" in (job.error or "")


def test_leaves_a_long_job_alone_while_its_worker_is_alive(db) -> None:
    # running for 2h is normal for a long live; what matters is the beat
    job, stream = _running_job(db, heartbeat=NOW - timedelta(seconds=30))

    assert reclaim_dead_jobs(db, JOB_TRANSCRIBE, NOW) == []
    assert job.status == JobStatus.RUNNING
    assert stream.status == StreamStatus.TRANSCRIBING


def test_requeues_legacy_running_job_that_never_had_a_heartbeat(db) -> None:
    # rows written before the heartbeat column existed
    job, _ = _running_job(db, heartbeat=None)

    assert [j.id for j in reclaim_dead_jobs(db, JOB_TRANSCRIBE, NOW)] == [job.id]
    assert job.status == JobStatus.QUEUED


def test_gives_up_on_a_job_that_keeps_killing_its_worker(db) -> None:
    job, stream = _running_job(db, heartbeat=DEAD, attempts=MAX_ATTEMPTS)

    reclaim_dead_jobs(db, JOB_TRANSCRIBE, NOW)

    assert job.status == JobStatus.FAILED, "must not requeue forever"
    assert stream.status == StreamStatus.FAILED
    assert job.finished_at is not None


def test_ignores_jobs_that_are_not_running(db) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    queued = add_job(db, stream, JOB_TRANSCRIBE, JobStatus.QUEUED)
    done = add_job(db, stream, JOB_TRANSCRIBE, JobStatus.DONE, finished_minutes_ago=90)
    db.flush()

    assert reclaim_dead_jobs(db, JOB_TRANSCRIBE, NOW) == []
    assert queued.status == JobStatus.QUEUED
    assert done.status == JobStatus.DONE


def test_only_touches_its_own_job_type(db) -> None:
    job, _ = _running_job(db, heartbeat=DEAD)

    assert reclaim_dead_jobs(db, "analyze", NOW) == []
    assert job.status == JobStatus.RUNNING
