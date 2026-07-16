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


def test_non_200_raises_transcription_error() -> None:
    transcriber = RemoteTranscriber(
        _settings(), client=_client(lambda r: httpx.Response(429, json={"error": "x"}))
    )
    with pytest.raises(TranscriptionError, match="429"):
        transcriber.transcribe(np.zeros(1600, dtype=np.float32))


def test_encode_wav_is_valid_pcm16() -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    data = _encode_wav(audio, SAMPLE_RATE)
    with wave.open(io.BytesIO(data)) as handle:
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 4
