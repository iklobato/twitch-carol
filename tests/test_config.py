import pytest

from core.config import Settings


def settings_without_env_file() -> Settings:
    # _env_file is a real pydantic-settings init kwarg missing from its stubs.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults() -> None:
    settings = settings_without_env_file()
    assert settings.whisper_model == "small"
    assert settings.whisper_compute_type == "int8"
    assert settings.llm_backend == "local"
    assert settings.llm_max_input_tokens == 30000
    assert settings.llm_max_output_tokens == 3000
    assert settings.simulation is False


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("SIMULATION", "1")
    monkeypatch.setenv("LLM_MAX_INPUT_TOKENS", "1000")
    settings = settings_without_env_file()
    assert settings.whisper_model == "tiny"
    assert settings.simulation is True
    assert settings.llm_max_input_tokens == 1000


def test_database_url_pins_psycopg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    # a bare postgresql:// URL (e.g. a DO App Platform DB binding) gets the
    # psycopg v3 driver; an explicit driver is left untouched.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:25060/db?sslmode=require")
    assert (
        settings_without_env_file().database_url
        == "postgresql+psycopg://u:p@host:25060/db?sslmode=require"
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host/db")
    assert (
        settings_without_env_file().database_url == "postgresql+psycopg://u:p@host/db"
    )
