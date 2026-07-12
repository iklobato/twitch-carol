import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from core.eventsub import (
    HEADER_MESSAGE_ID,
    HEADER_MESSAGE_TYPE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    SUBSCRIPTION_SPECS,
    compute_signature,
    specs_allowed_by_scopes,
    timestamp_is_fresh,
    verify_signature,
)
from core.queues import get_valkey

SECRET = "test-eventsub-secret"


class StubValkey:
    def __init__(self) -> None:
        self.store: set[str] = set()

    def set(self, key: str, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store.add(key)
        return True


def test_signature_round_trip() -> None:
    body = b'{"hello": "world"}'
    signature = compute_signature(SECRET, "msg-1", "2026-07-11T00:00:00Z", body)
    assert signature.startswith("sha256=")
    assert verify_signature(SECRET, "msg-1", "2026-07-11T00:00:00Z", signature, body)


def test_signature_rejects_tampered_body() -> None:
    signature = compute_signature(SECRET, "msg-1", "2026-07-11T00:00:00Z", b"original")
    assert not verify_signature(
        SECRET, "msg-1", "2026-07-11T00:00:00Z", signature, b"tampered"
    )


def test_timestamp_freshness() -> None:
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    fresh = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert timestamp_is_fresh(fresh, now=now)
    assert not timestamp_is_fresh(stale, now=now)
    assert not timestamp_is_fresh("not-a-date", now=now)


def test_specs_filtered_by_scopes() -> None:
    no_scopes = {spec.type for spec in specs_allowed_by_scopes([])}
    assert "stream.online" in no_scopes
    assert "channel.raid" in no_scopes
    assert "channel.subscribe" not in no_scopes

    with_subs = {
        spec.type for spec in specs_allowed_by_scopes(["channel:read:subscriptions"])
    }
    assert "channel.subscribe" in with_subs


def test_hype_train_uses_v2() -> None:
    versions = {spec.type: spec.version for spec in SUBSCRIPTION_SPECS}
    assert versions["channel.hype_train.begin"] == "2"
    assert versions["channel.follow"] == "2"


@pytest.fixture
def eventsub_client(
    monkeypatch: pytest.MonkeyPatch, twitch_env: None
) -> Iterator[TestClient]:
    monkeypatch.setenv("TWITCH_EVENTSUB_SECRET", SECRET)
    from core.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_valkey] = StubValkey
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _signed_headers(
    body: bytes, message_type: str, message_id: str = "msg-1"
) -> dict[str, str]:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        HEADER_MESSAGE_ID: message_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_MESSAGE_TYPE: message_type,
        HEADER_SIGNATURE: compute_signature(SECRET, message_id, timestamp, body),
    }


def test_callback_answers_verification_challenge(eventsub_client: TestClient) -> None:
    body = json.dumps({"challenge": "the-challenge-value"}).encode()
    response = eventsub_client.post(
        "/eventsub/callback",
        content=body,
        headers=_signed_headers(body, "webhook_callback_verification"),
    )
    assert response.status_code == 200
    assert response.text == "the-challenge-value"


def test_callback_rejects_bad_signature(eventsub_client: TestClient) -> None:
    body = b"{}"
    headers = _signed_headers(body, "notification")
    headers[HEADER_SIGNATURE] = "sha256=deadbeef"
    response = eventsub_client.post("/eventsub/callback", content=body, headers=headers)
    assert response.status_code == 403


def test_callback_rejects_stale_timestamp(eventsub_client: TestClient) -> None:
    body = b"{}"
    old = (datetime.now(UTC) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {
        HEADER_MESSAGE_ID: "msg-1",
        HEADER_TIMESTAMP: old,
        HEADER_MESSAGE_TYPE: "notification",
        HEADER_SIGNATURE: compute_signature(SECRET, "msg-1", old, body),
    }
    response = eventsub_client.post("/eventsub/callback", content=body, headers=headers)
    assert response.status_code == 403
