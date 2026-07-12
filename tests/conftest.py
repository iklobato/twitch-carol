from __future__ import annotations

import pytest
from better_profanity import profanity
from fastapi import WebSocketDisconnect

from alerts import StreamAlert
from config import Settings
from overlay import OverlayHub

REQUIRED_ENV_FIELDS = {
    "twitch_client_id": "cid",
    "twitch_client_secret": "csecret",
    "twitch_bot_id": "111",
    "twitch_owner_id": "222",
    "livepix_client_id": "lp-id",
    "livepix_client_secret": "lp-secret",
    "livepix_webhook_secret": "hook-secret",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Settings uses env_prefix="" so any ambient var named like a field leaks in.
    for name in REQUIRED_ENV_FIELDS:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _profanity_reset():
    # better_profanity is a module-level singleton; NsfwFilter mutates it with
    # no remove API, so restore the default English list after each test.
    yield
    profanity.load_censor_words()


@pytest.fixture
def make_settings():
    def factory(**overrides) -> Settings:
        fields = {**REQUIRED_ENV_FIELDS, **overrides}
        return Settings(_env_file=None, **fields)

    return factory


class FakeWebSocket:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.accepted = False
        self.sent: list[dict] = []
        self.fail_with = fail_with

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(payload)


@pytest.fixture
def fake_socket_factory():
    def factory(fail_with: Exception | None = None) -> FakeWebSocket:
        return FakeWebSocket(fail_with=fail_with)

    return factory


@pytest.fixture
def dead_socket_error() -> Exception:
    return WebSocketDisconnect(code=1006)


@pytest.fixture
def hub() -> OverlayHub:
    return OverlayHub()


class RecordingHub:
    def __init__(self) -> None:
        self.alerts: list[StreamAlert] = []

    async def broadcast(self, alert: StreamAlert) -> None:
        self.alerts.append(alert)


@pytest.fixture
def recording_hub() -> RecordingHub:
    return RecordingHub()
