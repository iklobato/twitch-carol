"""Sends one cold-email batch, one message per recipient, each carrying its own
/howto link token so the visit and the signup can be traced back to the person.

    python scripts/send_campaign_batch.py lote-2 [--dry-run]

Unlike a Resend broadcast this addresses everyone individually, which is what
makes per-person attribution possible. The cost of leaving broadcasts: the
List-Unsubscribe header is ours to send (Resend only injects it on broadcasts).

The token -> email map is written next to the batch CSV and stays on this
machine: production only ever learns the address of people who connect.
"""

from __future__ import annotations

import argparse
import csv
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.models import CampaignRecipient

BATCH_DIR = Path("data/campaign")
BODY_HTML = Path("ai-generated-messages/broadcast-body.html")
SUBJECT = "Ferramenta que analisa suas lives na Twitch (gratis na fase de testes)"
FROM = "Henrique <henrique@send.streamintel.cc>"
REPLY_TO = "tiktachack@gmail.com"
UNSUBSCRIBE_MAILTO = "<mailto:sair@streamintel.cc>"
HOWTO_URL = "https://streamintel.cc/howto"
RESEND_BATCH_URL = "https://api.resend.com/emails/batch"
RESEND_MAX_PER_CALL = 100
SECONDS_BETWEEN_CALLS = 1.0  # Resend allows 2 req/s; one per second is plenty
TOKEN_BYTES = 6  # 8 url-safe chars, inside the column's 16


def read_batch(batch: str) -> list[str]:
    path = BATCH_DIR / f"{batch}.csv"
    with path.open(newline="") as handle:
        return [row["email"].strip() for row in csv.DictReader(handle) if row["email"]]


def personalise(html: str, token: str) -> str:
    """Only the href carries the token: the visible link text stays clean, so
    the reader sees a plain streamintel.cc/howto and not a tracking string."""
    return html.replace(f'href="{HOWTO_URL}"', f'href="{HOWTO_URL}?e={token}"')


def build_messages(emails: list[str], html: str) -> list[dict]:
    messages = []
    for email in emails:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        messages.append(
            {
                "token": token,
                "payload": {
                    "from": FROM,
                    "to": [email],
                    "reply_to": REPLY_TO,
                    "subject": SUBJECT,
                    "html": personalise(html, token),
                    "headers": {"List-Unsubscribe": UNSUBSCRIBE_MAILTO},
                },
            }
        )
    return messages


def save_token_map(batch: str, emails: list[str], messages: list[dict]) -> Path:
    path = BATCH_DIR / f"tokens-{batch}.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["email", "token"])
        writer.writerows(
            [email, message["token"]] for email, message in zip(emails, messages, strict=True)
        )
    return path


def record_recipients(database_url: str, batch: str, messages: list[dict]) -> None:
    engine = create_engine(database_url)
    with Session(engine) as session:
        session.add_all(
            CampaignRecipient(token=message["token"], batch=batch) for message in messages
        )
        session.commit()
    engine.dispose()


def send(api_key: str, messages: list[dict]) -> None:
    headers = {"Authorization": f"Bearer {api_key}"}
    for start in range(0, len(messages), RESEND_MAX_PER_CALL):
        chunk = [m["payload"] for m in messages[start : start + RESEND_MAX_PER_CALL]]
        response = httpx.post(RESEND_BATCH_URL, headers=headers, json=chunk, timeout=30)
        response.raise_for_status()
        print(f"  enviados {start + len(chunk)}/{len(messages)}")
        time.sleep(SECONDS_BETWEEN_CALLS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", help="nome do lote, ex: lote-2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    emails = read_batch(args.batch)
    messages = build_messages(emails, BODY_HTML.read_text())
    token_map = save_token_map(args.batch, emails, messages)
    print(f"{len(emails)} destinatarios | mapa em {token_map}")

    if args.dry_run:
        print(f"dry-run: exemplo -> {messages[0]['payload']['to'][0]} ?e={messages[0]['token']}")
        return 0

    database_url = os.environ["DATABASE_URL"]
    api_key = os.environ["RESEND_API_KEY"]
    record_recipients(database_url, args.batch, messages)
    send(api_key, messages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
