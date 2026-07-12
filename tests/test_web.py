from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from livepix import LivePixAlertService, LivePixPayment, LivePixWebhookEvent
from web import build_app

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRET = "hook-secret"
VALID_BODY = {"resource": {"id": "pay-1", "type": "payment"}}


class RecordingService:
    def __init__(self) -> None:
        self.events: list[LivePixWebhookEvent] = []

    async def handle(self, event: LivePixWebhookEvent) -> None:
        self.events.append(event)


class StubPaymentClient:
    async def fetch_payment(self, resource_id: str) -> LivePixPayment:
        return LivePixPayment(amount=500, currency="BRL")


@pytest.fixture
def service() -> RecordingService:
    return RecordingService()


@pytest.fixture
def client(hub, service, make_settings) -> TestClient:
    app = build_app(hub, service, make_settings())
    return TestClient(app)


def test_get_overlay_serves_html_file(client):
    response = client.get("/overlay")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == (REPO_ROOT / "overlay.html").read_text(encoding="utf-8")


def test_static_overlay_js_is_served(client):
    response = client.get("/static/overlay.js")
    assert response.status_code == 200
    assert "function play(" in response.text


def test_webhook_valid_secret_and_body(client, service):
    response = client.post(f"/webhook/livepix/{SECRET}", json=VALID_BODY)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    [event] = service.events
    assert event.resource.id == "pay-1"
    assert event.resource.type == "payment"


def test_webhook_wrong_secret_is_403_and_not_handled(client, service):
    response = client.post("/webhook/livepix/wrong-secret", json=VALID_BODY)
    assert response.status_code == 403
    assert service.events == []


def test_webhook_wrong_length_secret_is_403(client, service):
    response = client.post("/webhook/livepix/x", json=VALID_BODY)
    assert response.status_code == 403
    assert service.events == []


def test_webhook_malformed_json_is_400(client, service):
    response = client.post(
        f"/webhook/livepix/{SECRET}",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert service.events == []


def test_webhook_schema_invalid_json_is_400(client, service):
    response = client.post(f"/webhook/livepix/{SECRET}", json={"resource": {"id": 1}})
    assert response.status_code == 400
    assert service.events == []


def test_webhook_bad_secret_takes_precedence_over_bad_body(client, service):
    response = client.post(
        "/webhook/livepix/wrong-secret",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 403


def test_websocket_lifecycle_registers_and_cleans_up(client, hub):
    with client.websocket_connect("/ws"):
        assert len(hub._connections) == 1
    assert len(hub._connections) == 0


def test_webhook_alert_reaches_connected_overlay(hub, make_settings):
    # End to end inside one event loop: the POST drives the broadcast, and the
    # TestClient websocket receives the alert payload.
    service = LivePixAlertService(StubPaymentClient(), hub)
    app = build_app(hub, service, make_settings())
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        response = client.post(f"/webhook/livepix/{SECRET}", json=VALID_BODY)
        assert response.status_code == 200
        payload = ws.receive_json()
    assert payload["kind"] == "pix_donation"
    assert payload["headline"] == "Pix recebido: R$5,00"
    assert "createdAt" in payload
