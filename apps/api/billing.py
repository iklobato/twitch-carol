"""Stripe billing: hosted Checkout to subscribe, hosted Billing Portal to
manage/cancel, and a signed webhook that syncs subscription state onto the
channel. No card data ever touches this app."""

import logging
from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.deps import CurrentChannel, DbSession
from core.config import get_settings
from core.models import Channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing")


class CheckoutUrl(BaseModel):
    url: str


def _require_billing_configured() -> None:
    settings = get_settings()
    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    stripe.api_key = settings.stripe_secret_key


@router.post("/checkout")
def create_checkout(channel: CurrentChannel) -> CheckoutUrl:
    _require_billing_configured()
    settings = get_settings()
    base = settings.public_base_url
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
        "success_url": f"{base}/?assinatura=sucesso",
        "cancel_url": f"{base}/?assinatura=cancelada",
        "client_reference_id": str(channel.id),
        # Partner codes: let the customer enter a promotion code, and skip the
        # card when a 100%-off code makes the total zero.
        "allow_promotion_codes": True,
        "payment_method_collection": "if_required",
    }
    if channel.stripe_customer_id:
        params["customer"] = channel.stripe_customer_id
    session = stripe.checkout.Session.create(**params)
    if session.url is None:
        raise HTTPException(status_code=502, detail="Stripe returned no checkout URL")
    return CheckoutUrl(url=session.url)


@router.get("/portal")
def create_portal(channel: CurrentChannel) -> CheckoutUrl:
    _require_billing_configured()
    if not channel.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No subscription to manage")
    session = stripe.billing_portal.Session.create(
        customer=channel.stripe_customer_id,
        return_url=get_settings().public_base_url + "/",
    )
    return CheckoutUrl(url=session.url)


def _apply_checkout_completed(db: Session, obj: dict) -> None:
    """Links the Stripe customer to the channel (subscription events only carry
    the customer id) and activates optimistically so activation never depends on
    webhook ordering."""
    channel_ref = obj.get("client_reference_id")
    customer_id = obj.get("customer")
    if channel_ref is None or customer_id is None:
        return
    channel = db.get(Channel, int(channel_ref))
    if channel is None:
        return
    channel.stripe_customer_id = str(customer_id)
    channel.subscription_status = "active"


def _apply_subscription_change(db: Session, obj: dict) -> None:
    channel = db.scalar(
        select(Channel).where(Channel.stripe_customer_id == obj["customer"])
    )
    if channel is None:
        return
    channel.subscription_status = obj["status"]
    period_end = obj.get("current_period_end")
    channel.current_period_end = (
        datetime.fromtimestamp(period_end, tz=UTC) if period_end else None
    )


_WEBHOOK_HANDLERS = {
    "checkout.session.completed": _apply_checkout_completed,
    "customer.subscription.created": _apply_subscription_change,
    "customer.subscription.updated": _apply_subscription_change,
    "customer.subscription.deleted": _apply_subscription_change,
}


@router.post("/webhook")
async def webhook(request: Request, db: DbSession) -> dict[str, str]:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as err:
        raise HTTPException(status_code=400, detail="Invalid webhook") from err

    handler = _WEBHOOK_HANDLERS.get(event["type"])
    if handler is not None:
        # Plain dict at the boundary: Stripe's StripeObject has no .get() and
        # its attribute access raises, so handlers stay simple dict readers.
        handler(db, event["data"]["object"].to_dict())
        db.commit()
        logger.info("stripe webhook applied", extra={"event_type": event["type"]})
    return {"status": "ok"}
