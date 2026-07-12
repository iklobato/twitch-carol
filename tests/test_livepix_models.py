from __future__ import annotations

import pytest
from pydantic import ValidationError

from livepix import (
    LivePixMessage,
    LivePixPayment,
    LivePixSubscription,
    LivePixWebhookEvent,
)


def test_webhook_event_parses_resource():
    event = LivePixWebhookEvent.model_validate(
        {"resource": {"id": "abc", "type": "payment"}}
    )
    assert event.resource.id == "abc"
    assert event.resource.type == "payment"


def test_webhook_event_requires_resource():
    with pytest.raises(ValidationError):
        LivePixWebhookEvent.model_validate({})


def test_message_defaults():
    message = LivePixMessage.model_validate({"amount": 500, "currency": "BRL"})
    assert message.username is None
    assert message.message is None
    assert message.flagged is False


def test_message_requires_amount_and_currency():
    with pytest.raises(ValidationError):
        LivePixMessage.model_validate({"username": "ana"})


def test_subscription_months_defaults_to_one():
    sub = LivePixSubscription.model_validate({"amount": 500, "currency": "BRL"})
    assert sub.months == 1
    assert sub.subscriber is None


def test_payment_rejects_non_int_amount():
    with pytest.raises(ValidationError):
        LivePixPayment.model_validate({"amount": "abc", "currency": "BRL"})
