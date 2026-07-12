from __future__ import annotations

from alerts import AlertKind
from livepix import (
    LivePixAlertService,
    LivePixMessage,
    LivePixPayment,
    LivePixSubscription,
    LivePixWebhookEvent,
)


class StubClient:
    def __init__(
        self,
        payment: LivePixPayment | None = None,
        message: LivePixMessage | None = None,
        subscription: LivePixSubscription | None = None,
    ) -> None:
        self.payment = payment
        self.message = message
        self.subscription = subscription
        self.fetched: list[tuple[str, str]] = []

    async def fetch_payment(self, resource_id: str) -> LivePixPayment:
        self.fetched.append(("payment", resource_id))
        return self.payment

    async def fetch_message(self, resource_id: str) -> LivePixMessage:
        self.fetched.append(("message", resource_id))
        return self.message

    async def fetch_subscription(self, resource_id: str) -> LivePixSubscription:
        self.fetched.append(("subscription", resource_id))
        return self.subscription


def event(resource_type: str, resource_id: str = "res-1") -> LivePixWebhookEvent:
    return LivePixWebhookEvent.model_validate(
        {"resource": {"id": resource_id, "type": resource_type}}
    )


async def test_unknown_resource_type_is_ignored(recording_hub):
    client = StubClient()
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("donation"))
    assert client.fetched == []
    assert recording_hub.alerts == []


async def test_payment_alert(recording_hub):
    client = StubClient(payment=LivePixPayment(amount=500, currency="BRL"))
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("payment", "pay-9"))
    assert client.fetched == [("payment", "pay-9")]
    [alert] = recording_hub.alerts
    assert alert.kind is AlertKind.PIX_DONATION
    assert alert.headline == "Pix recebido: R$5,00"
    assert alert.detail == "Obrigado pela doacao!"
    assert alert.username is None
    assert alert.amount.cents == 500


async def test_message_alert_normal(recording_hub):
    client = StubClient(
        message=LivePixMessage(
            username="Ana", message="valeu!", amount=1000, currency="BRL"
        )
    )
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("message"))
    [alert] = recording_hub.alerts
    assert alert.headline == "Ana doou R$10,00"
    assert alert.detail == "valeu!"
    assert alert.username == "Ana"


async def test_message_alert_anonymous(recording_hub):
    client = StubClient(
        message=LivePixMessage(message="oi", amount=1000, currency="BRL")
    )
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("message"))
    [alert] = recording_hub.alerts
    assert alert.headline == "Anonimo doou R$10,00"
    assert alert.username == "Anonimo"


async def test_message_alert_flagged_text_is_suppressed(recording_hub):
    client = StubClient(
        message=LivePixMessage(
            username="Ana",
            message="conteudo improprio",
            amount=1000,
            currency="BRL",
            flagged=True,
        )
    )
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("message"))
    [alert] = recording_hub.alerts
    assert "improprio" not in alert.detail
    assert alert.detail == "Obrigado pela doacao!"


async def test_message_alert_empty_message_uses_fallback(recording_hub):
    client = StubClient(message=LivePixMessage(amount=1000, currency="BRL"))
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("message"))
    [alert] = recording_hub.alerts
    assert alert.detail == "Obrigado pela doacao!"


async def test_subscription_alert(recording_hub):
    client = StubClient(
        subscription=LivePixSubscription(
            subscriber="Bea", months=3, amount=1500, currency="BRL"
        )
    )
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("subscription", "sub-7"))
    assert client.fetched == [("subscription", "sub-7")]
    [alert] = recording_hub.alerts
    assert alert.headline == "Bea assinou via Pix"
    assert alert.detail == "3 mes(es) - R$15,00"
    assert alert.username == "Bea"


async def test_subscription_alert_anonymous(recording_hub):
    client = StubClient(
        subscription=LivePixSubscription(amount=1500, currency="BRL")
    )
    service = LivePixAlertService(client, recording_hub)
    await service.handle(event("subscription"))
    [alert] = recording_hub.alerts
    assert alert.headline == "Anonimo assinou via Pix"
