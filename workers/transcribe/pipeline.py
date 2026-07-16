"""Post-live transcription: VAD -> region classification -> faster-whisper.

Product rules enforced here: music is marked `music` and its lyrics are never
transcribed or stored; silence is marked without text; only `speech` regions
reach the whisper model. Guest (multi-voice) detection is a stub for now:
cheap CPU diarization is an open problem, so no region is marked
guest_conversation yet (kind and plumbing exist; see _is_guest_conversation).
"""

import io
import logging
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
from sqlalchemy import delete
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.models import SegmentKind, Stream, TranscriptSegment
from core.storage import get_audio_storage
from workers.capture.collectors import AUDIO_SEGMENT_SECONDS

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Non-speech shorter than this merges into the surrounding flow (breaths,
# pauses); longer gets its own music/silence segment.
MIN_NONSPEECH_SECONDS = 5.0
SPEECH_MERGE_GAP_SECONDS = 1.0
# ponytail: RMS threshold separating music from silence in non-speech audio;
# calibrate against real captures when we have them (benchmark prints RMS).
MUSIC_RMS_THRESHOLD = 0.01


@dataclass(frozen=True)
class Region:
    start: float  # seconds within the audio file
    end: float
    kind: SegmentKind


def merge_speech_spans(
    spans: list[tuple[float, float]], max_gap: float = SPEECH_MERGE_GAP_SECONDS
) -> list[tuple[float, float]]:
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
            continue
        merged.append((start, end))
    return merged


def rms_energy(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))


def classify_regions(
    audio: np.ndarray, speech_spans: list[tuple[float, float]]
) -> list[Region]:
    """Speech spans come from VAD; the gaps between them are music when they
    still carry energy, silence otherwise."""
    total_seconds = len(audio) / SAMPLE_RATE
    regions: list[Region] = []
    cursor = 0.0
    for start, end in merge_speech_spans(speech_spans):
        if start - cursor >= MIN_NONSPEECH_SECONDS:
            regions.append(Region(cursor, start, _nonspeech_kind(audio, cursor, start)))
        regions.append(Region(start, end, _speech_kind()))
        cursor = end
    if total_seconds - cursor >= MIN_NONSPEECH_SECONDS:
        regions.append(
            Region(cursor, total_seconds, _nonspeech_kind(audio, cursor, total_seconds))
        )
    return regions


def _nonspeech_kind(audio: np.ndarray, start: float, end: float) -> SegmentKind:
    chunk = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
    if rms_energy(chunk) >= MUSIC_RMS_THRESHOLD:
        return SegmentKind.MUSIC
    return SegmentKind.SILENCE


def _speech_kind() -> SegmentKind:
    if _is_guest_conversation():
        return SegmentKind.GUEST_CONVERSATION
    return SegmentKind.SPEECH


def _is_guest_conversation() -> bool:
    # TODO(v1.x): multi-voice detection needs CPU-cheap diarization; until
    # then everything the VAD accepts is treated as the streamer's speech.
    return False


class Transcriber:
    """Lazy faster-whisper wrapper; one model instance per worker process."""

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            settings = get_settings()
            from faster_whisper import WhisperModel

            logger.info(
                "loading whisper model %s (%s)",
                settings.whisper_model,
                settings.whisper_compute_type,
            )
            self._model = WhisperModel(
                settings.whisper_model,
                device="cpu",
                compute_type=settings.whisper_compute_type,
            )
        return self._model

    def transcribe(self, audio: np.ndarray) -> list[tuple[float, float, str]]:
        """Returns (start, end, text) relative to the given audio chunk."""
        segments, _ = self._load().transcribe(
            audio, language="pt", beam_size=1, vad_filter=False
        )
        return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


class SpeechTranscriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> list[tuple[float, float, str]]: ...


class TranscriptionError(Exception):
    pass


def _encode_wav(audio: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return buf.getvalue()


class RemoteTranscriber:
    """Sends each audio chunk to a remote OpenAI-compatible transcription
    endpoint (Groq whisper-large-v3-turbo by default). No local model, so the
    worker stays light and long streams don't hog CPU."""

    TIMEOUT_SECONDS = 120.0
    MAX_ATTEMPTS = 3

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        retry_backoff: float = 1.0,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("TRANSCRIBE_BASE_URL", settings.transcribe_base_url),
                ("TRANSCRIBE_API_KEY", settings.transcribe_api_key),
                ("TRANSCRIBE_MODEL", settings.transcribe_model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"remote transcriber needs {', '.join(missing)}")
        self._url = settings.transcribe_base_url.rstrip("/") + "/audio/transcriptions"
        self._headers = {"Authorization": f"Bearer {settings.transcribe_api_key}"}
        self._model = settings.transcribe_model
        self._retry_backoff = retry_backoff
        self._client = client or httpx.Client(timeout=self.TIMEOUT_SECONDS)

    def transcribe(self, audio: np.ndarray) -> list[tuple[float, float, str]]:
        """Returns (start, end, text) relative to the given audio chunk.
        Retries on 429/5xx with backoff: transcription is idempotent and gets
        called once per speech chunk, so a transient throttle must not fail the
        whole stream."""
        wav = _encode_wav(audio, SAMPLE_RATE)
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            response = self._client.post(
                self._url,
                headers=self._headers,
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={
                    "model": self._model,
                    "language": "pt",
                    "response_format": "verbose_json",
                    "temperature": "0",
                },
            )
            if response.status_code == 200:
                segments = response.json().get("segments", [])
                return [
                    (s["start"], s["end"], s["text"].strip())
                    for s in segments
                    if s.get("text", "").strip()
                ]
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.MAX_ATTEMPTS:
                time.sleep(self._retry_backoff * attempt)
                continue
            raise TranscriptionError(
                f"transcription endpoint returned {response.status_code}"
            )
        raise TranscriptionError("transcription retries exhausted")


def get_transcriber() -> SpeechTranscriber:
    settings = get_settings()
    if settings.transcribe_backend == "remote":
        return RemoteTranscriber(settings)
    return Transcriber()


def detect_speech_spans(audio: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    timestamps = get_speech_timestamps(audio, VadOptions())
    return [(ts["start"] / SAMPLE_RATE, ts["end"] / SAMPLE_RATE) for ts in timestamps]


def process_stream(
    db: Session, stream: Stream, transcriber: SpeechTranscriber
) -> dict[str, int]:
    """Transcribes every stored audio segment of a stream into
    transcript_segments. Idempotent: reruns replace previous rows."""
    from faster_whisper.audio import decode_audio

    storage = get_audio_storage()
    prefix = f"audio/{stream.channel_id}/{stream.id}/"
    keys = storage.list_keys(prefix)
    logger.info(
        "transcribing %d audio file(s)",
        len(keys),
        extra={"stream_id": stream.id, "channel_id": stream.channel_id},
    )

    db.execute(
        delete(TranscriptSegment).where(TranscriptSegment.stream_id == stream.id)
    )
    counts = {kind.value: 0 for kind in SegmentKind}

    for key in keys:
        file_offset = _file_offset_seconds(key)
        with tempfile.NamedTemporaryFile(suffix=Path(key).suffix) as handle:
            storage.fetch_file(key, Path(handle.name))
            audio = decode_audio(handle.name, sampling_rate=SAMPLE_RATE)
        for region in classify_regions(audio, detect_speech_spans(audio)):
            counts[region.kind.value] += _persist_region(
                db, stream, transcriber, audio, region, file_offset
            )
    db.flush()
    return counts


def _file_offset_seconds(key: str) -> float:
    return int(Path(key).stem) * AUDIO_SEGMENT_SECONDS


def _absolute(stream: Stream, file_offset: float, seconds: float) -> datetime:
    return stream.started_at.astimezone(UTC) + timedelta(seconds=file_offset + seconds)


def _persist_region(
    db: Session,
    stream: Stream,
    transcriber: SpeechTranscriber,
    audio: np.ndarray,
    region: Region,
    file_offset: float,
) -> int:
    if region.kind is not SegmentKind.SPEECH:
        # music/silence/guest: timeline marker only, never any text
        db.add(
            TranscriptSegment(
                stream_id=stream.id,
                started_at=_absolute(stream, file_offset, region.start),
                ended_at=_absolute(stream, file_offset, region.end),
                kind=region.kind,
                text=None,
            )
        )
        return 1

    chunk = audio[int(region.start * SAMPLE_RATE) : int(region.end * SAMPLE_RATE)]
    added = 0
    for start, end, text in transcriber.transcribe(chunk):
        db.add(
            TranscriptSegment(
                stream_id=stream.id,
                started_at=_absolute(stream, file_offset, region.start + start),
                ended_at=_absolute(stream, file_offset, region.start + end),
                kind=SegmentKind.SPEECH,
                text=text,
            )
        )
        added += 1
    return added
