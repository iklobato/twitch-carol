from core.llm import TokenBudget, parse_json_object, truncate_to_tokens


def test_parse_json_object_unwraps_markdown_fence() -> None:
    """Anthropic through OpenRouter fences its answer even with
    response_format=json_object. Every reader shares this parser because the
    three that had their own copy silently discarded every recommendation."""
    assert parse_json_object('```json\n{"content": "oi"}\n```') == {"content": "oi"}
    assert parse_json_object('```\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('{"plain": true}') == {"plain": True}
    assert parse_json_object("not json at all") is None
    assert parse_json_object("[1, 2]") is None


class FakeBackend:
    """Tokenizer = whitespace words; deterministic and real enough to test
    budget arithmetic."""

    model_name = "fake"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def generate(self, prompt: str, max_tokens: int) -> str:
        return '{"content": "ok"}'


def test_truncate_keeps_text_within_token_cap() -> None:
    backend = FakeBackend()
    text = "um dois três quatro cinco seis"
    truncated = truncate_to_tokens(backend, text, 3)
    assert backend.count_tokens(truncated) <= 3
    assert truncated.startswith("um dois")


def test_truncate_returns_untouched_when_under_cap() -> None:
    backend = FakeBackend()
    assert truncate_to_tokens(backend, "um dois", 10) == "um dois"


def test_budget_spend_and_afford() -> None:
    budget = TokenBudget(FakeBackend(), max_input=10, max_output=5)
    assert budget.can_afford(10, 5)
    budget.spend("um dois três quatro", "cinco seis")  # 4 in, 2 out
    assert budget.input_remaining == 6
    assert budget.output_remaining == 3
    assert budget.input_spent == 4
    assert budget.output_spent == 2
    assert not budget.can_afford(7, 1)
    assert budget.can_afford(6, 3)


def test_fit_input_respects_remaining_budget() -> None:
    budget = TokenBudget(FakeBackend(), max_input=3, max_output=5)
    fitted = budget.fit_input("um dois três quatro cinco", cap=100)
    assert FakeBackend().count_tokens(fitted) <= 3


def test_an_unparseable_answer_is_logged_with_its_size_and_tail(caplog) -> None:
    cut_off = '{"topics": [{"name": "valorant", "evidence": "o jogo'

    with caplog.at_level("WARNING", logger="core.llm"):
        assert parse_json_object(cut_off) is None

    message = caplog.records[-1].getMessage()
    assert f"{len(cut_off)} chars" in message
    assert "o jogo" in message


def test_a_json_list_is_rejected_and_logged(caplog) -> None:
    with caplog.at_level("WARNING", logger="core.llm"):
        assert parse_json_object("[1, 2]") is None

    assert "top level is list" in caplog.records[-1].getMessage()
