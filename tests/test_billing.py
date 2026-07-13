"""Billing: the capture paywall (1 free live), /api/me flags, and the Stripe
webhook + checkout/portal endpoints. Stripe is exercised at its boundary only
(hand-signed webhooks, mocked SDK calls)."""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import pytest
import stripe
from sqlalchemy import select

from core.config import get_settings
from core.models import Channel, Stream
from tests.factories import make_channel, make_stream
from tests.test_eventsub_flow import post_notification

pytestmark = pytest.mark.usefixtures("fernet_key")

WEBHOOK_SECRET = "whsec_test"


@pytest.fixture
def eventsub_env(monkeypatch: pytest.MonkeyPatch, twitch_env: None) -> None:
    from tests.test_eventsub import SECRET

    monkeypatch.setenv("TWITCH_EVENTSUB_SECRET", SECRET)
    get_settings.cache_clear()


@pytest.fixture
def billing_env(monkeypatch: pytest.MonkeyPatch, twitch_env: None) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    get_settings.cache_clear()


def _online_event(channel: Channel) -> dict:
    return {
        "broadcaster_user_id": str(channel.twitch_user_id),
        "type": "live",
        "started_at": datetime.now(UTC).isoformat(),
    }


def _stream_count(db, channel: Channel) -> int:
    return len(db.scalars(select(Stream).where(Stream.channel_id == channel.id)).all())


# --- capture paywall (enforced in _handle_online) ---


def test_free_channel_gets_one_trial_live(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    assert post_notification(api_client, "stream.online", _online_event(channel)) == 204
    assert _stream_count(db, channel) == 1


def test_free_channel_second_live_is_not_captured(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    make_stream(db, channel)  # trial already used
    assert post_notification(api_client, "stream.online", _online_event(channel)) == 204
    assert _stream_count(db, channel) == 1


def test_pro_channel_captures_every_live(api_client, db, eventsub_env) -> None:
    channel = make_channel(db)
    make_stream(db, channel)
    channel.subscription_status = "active"
    db.flush()
    assert post_notification(api_client, "stream.online", _online_event(channel)) == 204
    assert _stream_count(db, channel) == 2


# --- /api/me flags ---


def test_me_reports_free_and_trial_state(api_client, db) -> None:
    from tests.conftest import login_as

    channel = make_channel(db)
    login_as(api_client, channel)

    body = api_client.get("/api/me").json()
    assert body["is_pro"] is False
    assert body["trial_used"] is False

    make_stream(db, channel)
    channel.subscription_status = "active"
    db.flush()
    body = api_client.get("/api/me").json()
    assert body["is_pro"] is True
    assert body["trial_used"] is True


# --- Stripe webhook ---


def _signed_headers(payload: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed = f"{timestamp}.".encode() + payload
    signature = hmac.new(WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={signature}"}


def _post_webhook(client, event: dict, headers: dict[str, str] | None = None):
    # Real Stripe events always carry a top-level object/id; construct_event
    # reads event.object, so the fixtures must include them.
    payload = json.dumps({"object": "event", "id": "evt_test", **event}).encode()
    return client.post(
        "/api/billing/webhook",
        content=payload,
        headers=headers or _signed_headers(payload),
    )


def test_checkout_completed_links_and_activates(api_client, db, billing_env) -> None:
    channel = make_channel(db)
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(channel.id),
                "customer": "cus_123",
            }
        },
    }
    assert _post_webhook(api_client, event).status_code == 200
    db.refresh(channel)
    assert channel.stripe_customer_id == "cus_123"
    assert channel.is_pro is True


def test_subscription_deleted_revokes_pro(api_client, db, billing_env) -> None:
    channel = make_channel(db)
    channel.stripe_customer_id = "cus_123"
    channel.subscription_status = "active"
    db.flush()
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_123", "status": "canceled"}},
    }
    assert _post_webhook(api_client, event).status_code == 200
    db.refresh(channel)
    assert channel.subscription_status == "canceled"
    assert channel.is_pro is False


def test_webhook_rejects_bad_signature(api_client, db, billing_env) -> None:
    channel = make_channel(db)
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {"client_reference_id": str(channel.id), "customer": "cus_9"}
        },
    }
    response = _post_webhook(
        api_client, event, headers={"Stripe-Signature": "t=1,v1=deadbeef"}
    )
    assert response.status_code == 400
    db.refresh(channel)
    assert channel.stripe_customer_id is None


# --- checkout / portal endpoints (Stripe SDK mocked at the boundary) ---


def test_checkout_returns_stripe_url(api_client, db, billing_env, monkeypatch) -> None:
    from tests.conftest import login_as

    channel = make_channel(db)
    login_as(api_client, channel)

    captured: dict = {}

    def fake_create(**params):
        captured.update(params)
        return stripe.checkout.Session.construct_from(
            {"url": "https://stripe.test/checkout"}, "sk_test"
        )

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    response = api_client.post("/api/billing/checkout")
    assert response.status_code == 200
    assert response.json()["url"] == "https://stripe.test/checkout"
    assert captured["client_reference_id"] == str(channel.id)
    assert captured["line_items"][0]["price"] == "price_test"


def test_portal_requires_customer(api_client, db, billing_env) -> None:
    from tests.conftest import login_as

    channel = make_channel(db)
    login_as(api_client, channel)
    assert api_client.get("/api/billing/portal").status_code == 400


def test_portal_returns_stripe_url(api_client, db, billing_env, monkeypatch) -> None:
    from tests.conftest import login_as

    channel = make_channel(db)
    channel.stripe_customer_id = "cus_123"
    db.flush()
    login_as(api_client, channel)

    def fake_create(**params):
        return stripe.billing_portal.Session.construct_from(
            {"url": "https://stripe.test/portal"}, "sk_test"
        )

    monkeypatch.setattr(stripe.billing_portal.Session, "create", fake_create)
    response = api_client.get("/api/billing/portal")
    assert response.status_code == 200
    assert response.json()["url"] == "https://stripe.test/portal"


# --- is_pro status logic (pure, no DB) ---


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", True),
        ("trialing", True),
        ("past_due", False),
        ("unpaid", False),
        ("canceled", False),
        ("incomplete", False),
        (None, False),
    ],
)
def test_is_pro_reflects_subscription_status(status, expected) -> None:
    assert Channel(subscription_status=status).is_pro is expected


# --- guards: billing off / unauthenticated ---


def test_checkout_requires_authentication(api_client, db, billing_env) -> None:
    assert api_client.post("/api/billing/checkout").status_code == 401


def test_checkout_returns_503_when_billing_not_configured(api_client, db) -> None:
    from tests.conftest import login_as

    get_settings.cache_clear()  # api_client set twitch_env only: no stripe keys
    channel = make_channel(db)
    login_as(api_client, channel)
    assert api_client.post("/api/billing/checkout").status_code == 503


def test_checkout_reuses_existing_customer(
    api_client, db, billing_env, monkeypatch
) -> None:
    from tests.conftest import login_as

    channel = make_channel(db)
    channel.stripe_customer_id = "cus_existing"
    db.flush()
    login_as(api_client, channel)

    captured: dict = {}

    def fake_create(**params):
        captured.update(params)
        return stripe.checkout.Session.construct_from(
            {"url": "https://stripe.test/checkout"}, "sk_test"
        )

    monkeypatch.setattr(stripe.checkout.Session, "create", fake_create)
    assert api_client.post("/api/billing/checkout").status_code == 200
    assert captured["customer"] == "cus_existing"


# --- webhook robustness: ordering, unknown/unhandled, period end ---


def test_subscription_event_for_unlinked_customer_is_ignored(
    api_client, db, billing_env
) -> None:
    # subscription.created can arrive before checkout.session.completed links
    # the customer; the handler must no-op instead of crashing.
    make_channel(db)
    event = {
        "type": "customer.subscription.created",
        "data": {"object": {"customer": "cus_unknown", "status": "active"}},
    }
    assert _post_webhook(api_client, event).status_code == 200


def test_unhandled_event_type_is_acked(api_client, db, billing_env) -> None:
    event = {"type": "invoice.paid", "data": {"object": {"id": "in_1"}}}
    assert _post_webhook(api_client, event).status_code == 200


def test_subscription_update_syncs_status_and_period_end(
    api_client, db, billing_env
) -> None:
    channel = make_channel(db)
    channel.stripe_customer_id = "cus_123"
    channel.subscription_status = "active"
    db.flush()
    period_end = 1893456000  # 2030-01-01 UTC
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "customer": "cus_123",
                "status": "past_due",
                "current_period_end": period_end,
            }
        },
    }
    assert _post_webhook(api_client, event).status_code == 200
    db.refresh(channel)
    assert channel.subscription_status == "past_due"
    assert channel.is_pro is False
    assert channel.current_period_end == datetime.fromtimestamp(period_end, tz=UTC)
