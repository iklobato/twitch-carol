"""Gradient serverless-inference backend (OpenAI-compatible HTTP)."""

import json

import httpx
import pytest

from core.config import Settings
from core.llm import GradientBackend, LLMError


def _settings(**over: object) -> Settings:
    values: dict[str, object] = {
        "llm_backend": "gradient",
        "gradient_endpoint": "https://inference.example.com/v1",
        "gradient_api_key": "key-123",
        "gradient_model": "qwen3-32b",
    }
    values.update(over)
    return Settings(**values)  # type: ignore[arg-type]  # dynamic kwargs into pydantic


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generate_posts_openai_shape_and_returns_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    backend = GradientBackend(_settings(), client=_mock_client(handler))
    out = backend.generate("diga oi", max_tokens=100)

    assert out == '{"ok": true}'
    body = seen["body"]
    assert isinstance(body, dict)
    assert str(seen["url"]).endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer key-123"
    assert body["model"] == "qwen3-32b"
    assert body["max_tokens"] == 100
    assert body["messages"][0]["content"] == "diga oi"


def test_generate_raises_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    backend = GradientBackend(_settings(), client=_mock_client(handler))
    with pytest.raises(LLMError, match="429"):
        backend.generate("x", max_tokens=10)


def test_count_tokens_is_conservative_estimate() -> None:
    backend = GradientBackend(
        _settings(), client=_mock_client(lambda r: httpx.Response(200))
    )
    assert backend.count_tokens("") == 1  # never zero
    assert backend.count_tokens("abcd") == 1  # 4 chars -> 1 token
    assert backend.count_tokens("a" * 9) == 3  # ceil(9/4)


def test_missing_config_raises() -> None:
    with pytest.raises(RuntimeError, match="GRADIENT_MODEL"):
        GradientBackend(_settings(gradient_model=""))
    with pytest.raises(RuntimeError, match="GRADIENT_API_KEY"):
        GradientBackend(_settings(gradient_api_key=""))
