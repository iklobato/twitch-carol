"""Resend email sender for the weekly/monthly digest (core.digest,
scripts/send_email_digests.py). Every call has a timeout; pass an
httpx.Client to reuse connections or inject a mock transport in tests
(same seam as core.twitch)."""

import logging
from contextlib import nullcontext

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
REQUEST_TIMEOUT_SECONDS = 10.0


class MailerError(Exception):
    """The send did NOT happen. Safe to try again."""


class MailerUncertain(MailerError):
    """The request left, but no answer came back (timeout, dropped
    connection). Resend may or may not have accepted it, so the caller must
    NOT send this digest again: a retry here is how one streamer gets the
    same recap twice."""


def _http(client: httpx.Client | None):
    if client is not None:
        return nullcontext(client)
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def send_email(
    to: str,
    subject: str,
    html: str,
    unsubscribe_url: str,
    client: httpx.Client | None = None,
) -> str:
    """Send one email via Resend. Returns the provider's message id, which
    the caller stores in EmailDigestLog.provider_message_id.

    unsubscribe_url also becomes the List-Unsubscribe header (RFC 8058 one
    click), separate from the link core.digest.render_html already puts in
    the body: mail clients that show their own "Unsubscribe" button read
    this header, not the body.
    """
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    payload = {
        "from": settings.digest_from,
        "to": [to],
        "subject": subject,
        "html": html,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    try:
        with _http(client) as http:
            response = http.post(RESEND_URL, headers=headers, json=payload)
    except httpx.RequestError as err:
        raise MailerUncertain(f"Resend did not answer: {err!r}") from err
    if response.status_code >= 300:
        raise MailerError(f"Resend returned {response.status_code}")
    message_id = response.json().get("id")
    if not message_id:
        raise MailerError("Resend response missing message id")
    return message_id
