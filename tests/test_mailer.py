import json
from typing import Any

import httpx
import pytest

from core.mailer import MailerError, MailerUncertain, send_email

pytestmark = pytest.mark.usefixtures("resend_env")


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_send_email_posts_to_resend_and_returns_the_message_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "msg_123"})

    message_id = send_email(
        "streamer@example.com",
        "Seu resumo semanal",
        "<p>oi</p>",
        "https://streamintel.cc/api/digest/unsubscribe?t=fake",
        client=_mock_client(handler),
    )

    assert message_id == "msg_123"
    assert seen["headers"]["authorization"] == "Bearer test-resend-key"
    assert seen["body"]["to"] == ["streamer@example.com"]
    assert seen["body"]["subject"] == "Seu resumo semanal"
    assert (
        seen["body"]["headers"]["List-Unsubscribe"]
        == "<https://streamintel.cc/api/digest/unsubscribe?t=fake>"
    )


def test_send_email_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from"})

    with pytest.raises(MailerError, match="422"):
        send_email(
            "streamer@example.com",
            "Subject",
            "<p>oi</p>",
            "https://streamintel.cc/api/digest/unsubscribe?t=fake",
            client=_mock_client(handler),
        )


def test_send_email_with_no_answer_raises_uncertain_not_a_plain_failure() -> None:
    """The caller retries a MailerError and must NOT retry this one: Resend
    may have accepted the email before the connection died."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    with pytest.raises(MailerUncertain):
        send_email(
            "streamer@example.com",
            "Subject",
            "<p>oi</p>",
            "https://streamintel.cc/api/digest/unsubscribe?t=fake",
            client=_mock_client(handler),
        )


def test_send_email_missing_message_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(MailerError, match="message id"):
        send_email(
            "streamer@example.com",
            "Subject",
            "<p>oi</p>",
            "https://streamintel.cc/api/digest/unsubscribe?t=fake",
            client=_mock_client(handler),
        )
