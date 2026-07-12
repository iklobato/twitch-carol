from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from config import Settings

REQUIRED = {
    "twitch_client_id",
    "twitch_client_secret",
    "twitch_bot_id",
    "twitch_owner_id",
    "livepix_client_id",
    "livepix_client_secret",
    "livepix_webhook_secret",
}


def test_missing_required_fields_raise_validation_error():
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    missing = {error["loc"][0] for error in excinfo.value.errors()}
    assert missing == REQUIRED


def test_defaults(make_settings):
    settings = make_settings()
    assert settings.twitch_prefix == "!"
    assert settings.twitch_thank_in_chat is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.nsfw_wordlist_path == Path("nsfw_words_pt.txt")
    assert settings.nsfw_delete_message is True
    assert settings.nsfw_timeout_seconds == 0


def test_env_vars_override_and_coerce(monkeypatch, make_settings):
    monkeypatch.setenv("TWITCH_PREFIX", "?")
    monkeypatch.setenv("NSFW_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("NSFW_DELETE_MESSAGE", "false")
    settings = make_settings()
    assert settings.twitch_prefix == "?"
    assert settings.nsfw_timeout_seconds == 60
    assert settings.nsfw_delete_message is False


def test_unknown_env_vars_are_ignored(monkeypatch, make_settings):
    monkeypatch.setenv("TOTALLY_UNRELATED_VAR", "boom")
    settings = make_settings()
    assert not hasattr(settings, "totally_unrelated_var")
