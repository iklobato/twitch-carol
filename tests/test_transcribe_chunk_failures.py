"""One speech chunk the endpoint keeps rejecting must not throw away a live.

Regression 2026-11-10: long lives send thousands of chunks, the endpoint
rejected one of them, and the whole transcription was discarded and restarted
from zero (54 minutes of work on a 149-file live), then failed for good on the
third try. A chunk that still fails after its own retries is now skipped and
logged; the live fails only when too many chunks fail, which means the endpoint
itself is down."""

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import workers.transcribe.pipeline as pipeline
from core.models import SegmentKind, TranscriptSegment
from tests.factories import make_channel, make_stream
from workers.transcribe.pipeline import (
    SAMPLE_RATE,
    Region,
    Transcription,
    TranscriptionError,
    process_stream,
)

SPEECH_CHUNKS = 200
CHUNK_SECONDS = 2.0
FILE_SECONDS = SPEECH_CHUNKS * CHUNK_SECONDS


class OneFileStorage:
    def list_keys(self, prefix: str) -> list[str]:
        return [f"{prefix}000.ogg"]

    def fetch_file(self, key: str, destination: Path) -> None:
        destination.write_bytes(b"ogg")


class SpeechEverywhere:
    """Classifies the file as back-to-back speech chunks."""

    def regions(self, audio: np.ndarray, spans: list) -> list[Region]:
        return [
            Region(index * CHUNK_SECONDS, (index + 1) * CHUNK_SECONDS, SegmentKind.SPEECH)
            for index in range(SPEECH_CHUNKS)
        ]


class RejectingTranscriber:
    """Rejects the chunks whose call number is in `rejected`, transcribes the rest."""

    def __init__(self, rejected: set[int]) -> None:
        self._rejected = rejected
        self._calls = 0

    def transcribe(self, audio: np.ndarray) -> Transcription:
        self._calls += 1
        if self._calls in self._rejected:
            raise TranscriptionError("transcription endpoint returned 400: upstream")
        return Transcription(language="pt", segments=[(0.0, 1.0, "fala")])


@pytest.fixture
def one_long_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "get_audio_storage", OneFileStorage)
    monkeypatch.setattr(
        "faster_whisper.audio.decode_audio",
        lambda path, sampling_rate: np.zeros(int(FILE_SECONDS * SAMPLE_RATE), dtype=np.float32),
    )
    monkeypatch.setattr(pipeline, "detect_speech_spans", lambda audio: [])
    monkeypatch.setattr(pipeline, "classify_regions", SpeechEverywhere().regions)


def test_one_rejected_chunk_keeps_the_rest_of_the_live(db: Session, one_long_file: None) -> None:
    stream = make_stream(db, make_channel(db))

    counts = process_stream(db, stream, RejectingTranscriber(rejected={1}))

    stored = db.scalar(
        select(func.count())
        .select_from(TranscriptSegment)
        .where(TranscriptSegment.stream_id == stream.id)
    )
    assert stored == SPEECH_CHUNKS - 1, f"{stored} segments kept of {SPEECH_CHUNKS - 1}"
    assert counts["untranscribed"] == 1, f"skipped chunks not reported: {counts}"


def test_endpoint_down_still_fails_the_live(db: Session, one_long_file: None) -> None:
    stream = make_stream(db, make_channel(db))
    every_chunk = set(range(1, SPEECH_CHUNKS + 1))

    with pytest.raises(TranscriptionError, match=f"{SPEECH_CHUNKS} of {SPEECH_CHUNKS}"):
        process_stream(db, stream, RejectingTranscriber(rejected=every_chunk))
