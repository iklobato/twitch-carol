"""Remote transcription backend (Groq/OpenAI-compatible /audio/transcriptions)."""

import io
import wave

import httpx
import numpy as np
import pytest

from core.config import Settings
from workers.transcribe.pipeline import (
    SAMPLE_RATE,
    RemoteTranscriber,
    TranscriptionError,
    _encode_wav,
)

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
TENTH_OF_A_SECOND = SAMPLE_RATE // 10


def _settings(**over: object) -> Settings:
    values: dict[str, object] = {
        "transcribe_backend": "remote",
        "transcribe_base_url": "https://api.groq.com/openai/v1",
        "transcribe_api_key": "gsk-key",
        "transcribe_model": "whisper-large-v3-turbo",
    }
    values.update(over)
    return Settings(**values)  # type: ignore[arg-type]  # dynamic kwargs into pydantic


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_transcribe_posts_audio_and_parses_segments() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "language": "pt",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": " olá mundo "},
                    {"start": 1.5, "end": 2.0, "text": "   "},
                ]
            },
        )

    transcriber = RemoteTranscriber(_settings(), client=_client(handler))
    out = transcriber.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))

    assert out.segments == [(0.0, 1.5, "olá mundo")]  # blank-text segment dropped
    assert out.language == "pt"  # reported by the model, not asked for
    assert str(seen["url"]).endswith("/audio/transcriptions")
    assert seen["auth"] == "Bearer gsk-key"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b"whisper-large-v3-turbo" in body
    assert b'name="file"' in body
    # no language is sent at all: telling Whisper the wrong one makes it
    # transcribe phonetically, and every insight is then built on nonsense.
    # It reads the audio; we read its answer.
    assert b'name="language"' not in body


def test_missing_config_raises() -> None:
    with pytest.raises(RuntimeError, match="TRANSCRIBE_API_KEY"):
        RemoteTranscriber(_settings(transcribe_api_key=""))
    with pytest.raises(RuntimeError, match="TRANSCRIBE_MODEL"):
        RemoteTranscriber(_settings(transcribe_model=""))


def test_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(
            200, json={"segments": [{"start": 0, "end": 1, "text": "oi"}]}
        )

    transcriber = RemoteTranscriber(
        _settings(), client=_client(handler), retry_backoff=0
    )
    out = transcriber.transcribe(np.zeros(1600, dtype=np.float32))
    assert out.segments == [(0, 1, "oi")]
    assert calls["n"] == 2  # first 429, retried once


def test_exhausts_retries_then_raises() -> None:
    transcriber = RemoteTranscriber(
        _settings(),
        client=_client(lambda r: httpx.Response(429, json={"error": "x"})),
        retry_backoff=0,
    )
    with pytest.raises(TranscriptionError, match="429"):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32))


def test_auth_error_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(HTTP_UNAUTHORIZED, json={"error": "bad key"})

    transcriber = RemoteTranscriber(
        _settings(), client=_client(handler), retry_backoff=0
    )
    with pytest.raises(TranscriptionError, match="401"):
        transcriber.transcribe(np.zeros(TENTH_OF_A_SECOND, dtype=np.float32))
    assert calls["n"] == 1  # a wrong key does not fix itself on a retry


def test_400_is_retried_then_succeeds() -> None:
    """Regression 2026-11-10: the endpoint (OpenRouter) answered 400 once in
    thousands of chunks on long lives; the same chunk passes when sent again."""
    answers = iter([
        httpx.Response(HTTP_BAD_REQUEST, json={"error": "upstream"}),
        httpx.Response(HTTP_OK, json={"language": "pt", "segments": []}),
    ])
    transcriber = RemoteTranscriber(
        _settings(), client=_client(lambda request: next(answers)), retry_backoff=0
    )

    out = transcriber.transcribe(np.zeros(TENTH_OF_A_SECOND, dtype=np.float32))

    assert out.language == "pt", "a 400 that passes on the second try still failed"


def test_rejection_carries_the_endpoint_message() -> None:
    """The 400s of 2026-11-10 could not be diagnosed: the body was thrown away."""
    rejected = httpx.Response(HTTP_BAD_REQUEST, json={"error": "audio too long"})
    transcriber = RemoteTranscriber(
        _settings(), client=_client(lambda request: rejected), retry_backoff=0
    )

    with pytest.raises(TranscriptionError, match="400.*audio too long"):
        transcriber.transcribe(np.zeros(TENTH_OF_A_SECOND, dtype=np.float32))


def test_encode_wav_is_valid_pcm16() -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    data = _encode_wav(audio, SAMPLE_RATE)
    with wave.open(io.BytesIO(data)) as handle:
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 4
