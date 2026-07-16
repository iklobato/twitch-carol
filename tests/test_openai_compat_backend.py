"""Remote OpenAI-compatible LLM backend (Gradient/OpenRouter/OpenAI over HTTP)."""

import json

import httpx
import pytest

from core.config import Settings
from core.llm import LLMError, OpenAICompatBackend


def _settings(**over: object) -> Settings:
    values: dict[str, object] = {
        "llm_backend": "openai",
        "llm_base_url": "https://openrouter.ai/api/v1",
        "llm_api_key": "key-123",
        "llm_model": "meta-llama/llama-3.3-70b-instruct",
        # pinned so the base case doesn't inherit a real .env value
        "llm_require_provider_params": False,
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

    backend = OpenAICompatBackend(_settings(), client=_mock_client(handler))
    out = backend.generate("diga oi", max_tokens=100)

    assert out == '{"ok": true}'
    body = seen["body"]
    assert isinstance(body, dict)
    assert str(seen["url"]).endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer key-123"
    assert body["model"] == "meta-llama/llama-3.3-70b-instruct"
    assert body["max_tokens"] == 100
    assert body["messages"][0]["content"] == "diga oi"
    assert body["response_format"] == {"type": "json_object"}
    assert "provider" not in body  # flag off by default


def test_require_provider_params_adds_provider_routing() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    backend = OpenAICompatBackend(
        _settings(llm_require_provider_params=True), client=_mock_client(handler)
    )
    backend.generate("x", max_tokens=10)

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["provider"] == {"require_parameters": True}


def test_model_override_used_for_strong_tasks() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    backend = OpenAICompatBackend(
        _settings(), client=_mock_client(handler), model="anthropic/claude-sonnet-4.6"
    )
    assert backend.model_name == "anthropic/claude-sonnet-4.6"
    backend.generate("x", max_tokens=10)
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "anthropic/claude-sonnet-4.6"


def test_generate_raises_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    backend = OpenAICompatBackend(_settings(), client=_mock_client(handler))
    with pytest.raises(LLMError, match="429"):
        backend.generate("x", max_tokens=10)


def test_count_tokens_is_conservative_estimate() -> None:
    backend = OpenAICompatBackend(
        _settings(), client=_mock_client(lambda r: httpx.Response(200))
    )
    assert backend.count_tokens("") == 1  # never zero
    assert backend.count_tokens("abcd") == 1  # 4 chars -> 1 token
    assert backend.count_tokens("a" * 9) == 3  # ceil(9/4)


def test_missing_config_raises() -> None:
    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        OpenAICompatBackend(_settings(llm_model=""))
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        OpenAICompatBackend(_settings(llm_api_key=""))
