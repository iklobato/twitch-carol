from __future__ import annotations

import logging
from typing import Awaitable, Callable

import httpx
from pydantic import BaseModel

from alerts import AlertKind, Money, StreamAlert
from config import Settings
from overlay import OverlayHub

logger = logging.getLogger(__name__)

LIVEPIX_API_BASE = "https://api.livepix.gg"
LIVEPIX_TOKEN_URL = "https://oauth.livepix.gg/oauth2/token"
LIVEPIX_SCOPES = "payments:read messages:read subscriptions:read"


class LivePixResource(BaseModel):
    id: str
    type: str


class LivePixWebhookEvent(BaseModel):
    resource: LivePixResource


class LivePixPayment(BaseModel):
    amount: int
    currency: str


class LivePixMessage(BaseModel):
    username: str | None = None
    message: str | None = None
    amount: int
    currency: str
    flagged: bool = False


class LivePixSubscription(BaseModel):
    subscriber: str | None = None
    months: int = 1
    amount: int
    currency: str


class LivePixClient:
    def __init__(self, settings: Settings) -> None:
        self._client_id = settings.livepix_client_id
        self._client_secret = settings.livepix_client_secret
        self._http = httpx.AsyncClient(base_url=LIVEPIX_API_BASE, timeout=10.0)
        self._token: str | None = None

    async def __aenter__(self) -> "LivePixClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._http.aclose()

    async def _authorize(self) -> str:
        if self._token:
            return self._token
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                LIVEPIX_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": LIVEPIX_SCOPES,
                },
            )
        response.raise_for_status()
        self._token = response.json()["access_token"]
        return self._token

    async def _get(self, path: str) -> dict:
        token = await self._authorize()
        response = await self._http.get(
            path, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            self._token = None
        response.raise_for_status()
        return response.json()

    async def fetch_payment(self, resource_id: str) -> LivePixPayment:
        return LivePixPayment.model_validate(
            await self._get(f"/v2/payments/{resource_id}")
        )

    async def fetch_message(self, resource_id: str) -> LivePixMessage:
        return LivePixMessage.model_validate(
            await self._get(f"/v2/messages/{resource_id}")
        )

    async def fetch_subscription(self, resource_id: str) -> LivePixSubscription:
        return LivePixSubscription.model_validate(
            await self._get(f"/v2/subscriptions/{resource_id}")
        )


class LivePixAlertService:
    def __init__(self, client: LivePixClient, hub: OverlayHub) -> None:
        self._client = client
        self._hub = hub
        self._handlers: dict[str, Callable[[str], Awaitable[StreamAlert]]] = {
            "payment": self._payment_alert,
            "message": self._message_alert,
            "subscription": self._subscription_alert,
        }

    async def handle(self, event: LivePixWebhookEvent) -> None:
        handler = self._handlers.get(event.resource.type)
        if handler is None:
            logger.info("ignoring LivePix resource type %r", event.resource.type)
            return
        alert = await handler(event.resource.id)
        await self._hub.broadcast(alert)

    async def _payment_alert(self, resource_id: str) -> StreamAlert:
        payment = await self._client.fetch_payment(resource_id)
        money = Money.from_livepix(payment.amount, payment.currency)
        return StreamAlert(
            kind=AlertKind.PIX_DONATION,
            headline=f"Pix recebido: {money.format()}",
            detail="Obrigado pela doacao!",
            amount=money,
        )

    async def _message_alert(self, resource_id: str) -> StreamAlert:
        message = await self._client.fetch_message(resource_id)
        money = Money.from_livepix(message.amount, message.currency)
        who = message.username or "Anonimo"
        text = "" if message.flagged else (message.message or "")
        return StreamAlert(
            kind=AlertKind.PIX_DONATION,
            headline=f"{who} doou {money.format()}",
            detail=text or "Obrigado pela doacao!",
            username=who,
            amount=money,
        )

    async def _subscription_alert(self, resource_id: str) -> StreamAlert:
        sub = await self._client.fetch_subscription(resource_id)
        money = Money.from_livepix(sub.amount, sub.currency)
        who = sub.subscriber or "Anonimo"
        return StreamAlert(
            kind=AlertKind.PIX_DONATION,
            headline=f"{who} assinou via Pix",
            detail=f"{sub.months} mes(es) - {money.format()}",
            username=who,
            amount=money,
        )
