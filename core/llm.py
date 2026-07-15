"""LLM backends. Local CPU (llama.cpp) or DigitalOcean Gradient serverless
inference (OpenAI-compatible HTTP), selected by LLM_BACKEND.

The local backend budgets with the model's real tokenizer; the remote one has
no local tokenizer, so it approximates (see GradientBackend.count_tokens).
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# context = full input budget + output + prompt-template slack
N_CTX_SLACK_TOKENS = 512


class LLMBackend(Protocol):
    model_name: str

    def count_tokens(self, text: str) -> int: ...

    def generate(self, prompt: str, max_tokens: int) -> str: ...


class LocalLlamaBackend:
    def __init__(self, settings: Settings) -> None:
        from llama_cpp import Llama

        if not settings.llm_gguf_path:
            raise RuntimeError("LLM_GGUF_PATH is not set")
        self.model_name = Path(settings.llm_gguf_path).name
        self._llama = Llama(
            model_path=settings.llm_gguf_path,
            n_ctx=settings.llm_max_input_tokens
            + settings.llm_max_output_tokens
            + N_CTX_SLACK_TOKENS,
            n_threads=None,  # llama.cpp picks the core count
            verbose=False,
        )

    def count_tokens(self, text: str) -> int:
        return len(self._llama.tokenize(text.encode(), add_bos=False))

    def generate(self, prompt: str, max_tokens: int) -> str:
        response = self._llama.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return response["choices"][0]["message"]["content"]


class LLMError(Exception):
    pass


class GradientBackend:
    """DigitalOcean Gradient serverless inference over its OpenAI-compatible
    endpoint. No local model: requests go over HTTP with an app-level API key."""

    CHARS_PER_TOKEN = 4
    TIMEOUT_SECONDS = 120.0

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        missing = [
            name
            for name, value in (
                ("GRADIENT_ENDPOINT", settings.gradient_endpoint),
                ("GRADIENT_API_KEY", settings.gradient_api_key),
                ("GRADIENT_MODEL", settings.gradient_model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"gradient backend needs {', '.join(missing)}")
        self.model_name = settings.gradient_model
        self._url = settings.gradient_endpoint.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {settings.gradient_api_key}"}
        self._client = client or httpx.Client(timeout=self.TIMEOUT_SECONDS)

    def count_tokens(self, text: str) -> int:
        """Char-based approximation (~4 chars/token): the remote model's
        tokenizer isn't local. Used only to size the budget; the hard output
        limit is enforced by max_tokens on the request."""
        return max(1, -(-len(text) // self.CHARS_PER_TOKEN))

    def generate(self, prompt: str, max_tokens: int) -> str:
        response = self._client.post(
            self._url,
            headers=self._headers,
            json={
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        )
        if response.status_code != 200:
            raise LLMError(f"Gradient inference returned {response.status_code}")
        return response.json()["choices"][0]["message"]["content"]


_BACKENDS: dict[str, Callable[[Settings], LLMBackend]] = {
    "local": LocalLlamaBackend,
    "gradient": GradientBackend,
}


def get_llm_backend() -> LLMBackend:
    settings = get_settings()
    backend_class = _BACKENDS.get(settings.llm_backend)
    if backend_class is None:
        raise RuntimeError(f"Unknown LLM_BACKEND: {settings.llm_backend}")
    return backend_class(settings)


def truncate_to_tokens(backend: LLMBackend, text: str, max_tokens: int) -> str:
    """Binary-search truncation using the real tokenizer."""
    if backend.count_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if backend.count_tokens(text[:mid]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low]


class TokenBudget:
    """Hard per-stream budget. Every prompt/response must pass through here;
    when the input budget runs out, lower-priority LLM steps are skipped."""

    def __init__(self, backend: LLMBackend, max_input: int, max_output: int) -> None:
        self._backend = backend
        self.input_remaining = max_input
        self.output_remaining = max_output
        self.input_spent = 0
        self.output_spent = 0

    def can_afford(self, input_tokens: int, output_tokens: int) -> bool:
        return (
            input_tokens <= self.input_remaining
            and output_tokens <= self.output_remaining
        )

    def fit_input(self, text: str, cap: int) -> str:
        return truncate_to_tokens(self._backend, text, min(cap, self.input_remaining))

    def spend(self, prompt: str, response: str) -> None:
        input_tokens = self._backend.count_tokens(prompt)
        output_tokens = self._backend.count_tokens(response)
        self.input_remaining = max(0, self.input_remaining - input_tokens)
        self.output_remaining = max(0, self.output_remaining - output_tokens)
        self.input_spent += input_tokens
        self.output_spent += output_tokens
