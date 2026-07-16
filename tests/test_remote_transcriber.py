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
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": " olá mundo "},
                    {"start": 1.5, "end": 2.0, "text": "   "},
                ]
            },
        )

    transcriber = RemoteTranscriber(_settings(), client=_client(handler))
    out = transcriber.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))

    assert out == [(0.0, 1.5, "olá mundo")]  # blank-text segment dropped
    assert str(seen["url"]).endswith("/audio/transcriptions")
    assert seen["auth"] == "Bearer gsk-key"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b"whisper-large-v3-turbo" in body
    assert b'name="file"' in body
    assert b'name="language"' in body


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
    assert out == [(0, 1, "oi")]
    assert calls["n"] == 2  # first 429, retried once


def test_exhausts_retries_then_raises() -> None:
    transcriber = RemoteTranscriber(
        _settings(),
        client=_client(lambda r: httpx.Response(429, json={"error": "x"})),
        retry_backoff=0,
    )
    with pytest.raises(TranscriptionError, match="429"):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32))


def test_client_error_raises_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad audio"})

    transcriber = RemoteTranscriber(
        _settings(), client=_client(handler), retry_backoff=0
    )
    with pytest.raises(TranscriptionError, match="400"):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32))
    assert calls["n"] == 1  # 4xx (non-429) not retried


def test_encode_wav_is_valid_pcm16() -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    data = _encode_wav(audio, SAMPLE_RATE)
    with wave.open(io.BytesIO(data)) as handle:
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 4
