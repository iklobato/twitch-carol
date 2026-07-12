"""Job lifecycle against the DB: priority picking, success transitions,
retry and permanent failure."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from core import worker_loop
from core.models import Job, JobStatus, StreamStatus
from core.queues import JOB_ANALYZE, JOB_TRANSCRIBE, QUEUE_KEYS
from core.worker_loop import MAX_ATTEMPTS, WorkerSpec, _run_job, pick_next_job
from tests.factories import add_job, make_channel, make_stream

SPEC = WorkerSpec(
    job_type=JOB_TRANSCRIBE,
    running_status=StreamStatus.TRANSCRIBING,
    done_status=StreamStatus.QUEUED_ANALYSIS,
    next_job_type=JOB_ANALYZE,
)


@pytest.fixture
def valkey_patch(monkeypatch: pytest.MonkeyPatch, fake_valkey):
    monkeypatch.setattr(worker_loop, "get_valkey", lambda: fake_valkey)
    return fake_valkey


def test_pick_next_job_prefers_most_urgent_channel(db) -> None:
    soon = make_channel(db)
    for weeks in (1, 2):
        make_stream(db, soon, started_minutes_ago=weeks * 7 * 24 * 60 - 60)
    later = make_channel(db)
    make_stream(db, later, started_minutes_ago=3 * 24 * 60)

    later_job = add_job(
        db, make_stream(db, later, StreamStatus.QUEUED_TRANSCRIPTION), JOB_TRANSCRIBE
    )
    soon_job = add_job(
        db, make_stream(db, soon, StreamStatus.QUEUED_TRANSCRIPTION), JOB_TRANSCRIBE
    )

    picked = pick_next_job(db, JOB_TRANSCRIBE, datetime.now(UTC))
    assert picked is not None
    assert picked.id == soon_job.id
    assert picked.id != later_job.id


def test_pick_next_job_none_when_empty(db) -> None:
    assert pick_next_job(db, JOB_TRANSCRIBE, datetime.now(UTC)) is None


def test_run_job_success_transitions_and_chains_next_job(db, valkey_patch) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.QUEUED_TRANSCRIPTION)
    job = add_job(db, stream, JOB_TRANSCRIBE)
    seen_statuses = []

    def handler(handler_db, handler_stream):
        seen_statuses.append(handler_stream.status)
        return {"ok": True}

    _run_job(db, SPEC, job, handler)

    db.refresh(job)
    db.refresh(stream)
    assert seen_statuses == [StreamStatus.TRANSCRIBING]
    assert job.status == JobStatus.DONE
    assert job.finished_at is not None
    assert stream.status == StreamStatus.QUEUED_ANALYSIS
    chained = db.scalars(
        select(Job).where(Job.stream_id == stream.id).where(Job.type == JOB_ANALYZE)
    ).all()
    assert len(chained) == 1
    assert valkey_patch.streams[QUEUE_KEYS[JOB_ANALYZE]][0]["stream_id"] == str(
        stream.id
    )


def test_run_job_failure_requeues_then_fails_permanently(db, valkey_patch) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel, StreamStatus.QUEUED_TRANSCRIPTION)
    job = add_job(db, stream, JOB_TRANSCRIBE)

    def broken_handler(handler_db, handler_stream):
        raise RuntimeError("boom")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        _run_job(db, SPEC, job, broken_handler)
        db.refresh(job)
        assert job.attempts == attempt
        assert "boom" in (job.error or "")
        if attempt < MAX_ATTEMPTS:
            assert job.status == JobStatus.QUEUED

    db.refresh(stream)
    assert job.status == JobStatus.FAILED
    assert stream.status == StreamStatus.FAILED
    assert (
        db.scalars(
            select(Job).where(Job.stream_id == stream.id).where(Job.type == JOB_ANALYZE)
        ).all()
        == []
    )


def test_run_job_with_missing_stream_fails_cleanly(db, valkey_patch) -> None:
    channel = make_channel(db)
    stream = make_stream(db, channel)
    job = add_job(db, stream, JOB_TRANSCRIBE)
    job.stream_id = stream.id
    db.flush()
    orphan = Job(type=JOB_TRANSCRIBE, stream_id=stream.id, status=JobStatus.QUEUED)
    db.add(orphan)
    db.flush()
    # simulate the stream vanishing between pick and run
    stream_id = stream.id
    orphan_id = orphan.id

    class GhostDb:
        def get(self, model, key):
            return None if key == stream_id else db.get(model, key)

        def commit(self):
            db.commit()

    ghost_job = db.get(Job, orphan_id)
    _run_job(GhostDb(), SPEC, ghost_job, lambda a, b: None)  # type: ignore[arg-type]
    db.refresh(ghost_job)
    assert ghost_job.status == JobStatus.FAILED
    assert "not found" in (ghost_job.error or "")
