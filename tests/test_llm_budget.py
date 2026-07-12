from core.llm import TokenBudget, truncate_to_tokens


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
