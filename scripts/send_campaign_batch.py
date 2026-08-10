"""Envia um lote do convite beta pelo Resend, um email por destinatario.

    python scripts/send_campaign_batch.py lote-6 [--dry-run]

Sem rastreamento por pessoa: o link do /howto vai limpo e igual para todo mundo.

O cabecalho List-Unsubscribe aqui e nosso: fora do broadcast o Resend nao
injeta nada. O marcador {{{RESEND_UNSUBSCRIBE_URL}}} do arquivo de broadcast so
e substituido dentro de um broadcast, entao esse paragrafo sai inteiro no envio
por API. Trocar por um mailto era pior: link apontando para fora do dominio
remetente e sinal de spam (o proprio Resend acusa), e o convite ja tem o opt-out
humano, o "responda sair", que chega no reply-to.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

import httpx

BATCH_DIR = Path("data/campaign")
# Um corpo e um assunto por idioma. Convite em portugues para canal em ingles
# rende reclamacao de spam, que e o unico numero que o portao trata como fatal.
BODY_HTML = {
    "pt": Path("ai-generated-messages/broadcast-body.html"),
    "en": Path("ai-generated-messages/broadcast-body-en.html"),
}
SUBJECT = {
    "pt": "Ferramenta que analisa suas lives na Twitch (gratis na fase de testes)",
    "en": "I built a tool that analyses your Twitch streams (free while in beta)",
}
DEFAULT_LANGUAGE = "pt"
FROM = "Henrique <henrique@send.streamintel.cc>"
# Mesmo endereco do remetente, e uma caixa de verdade: IMAP no droplet
# mail.iklobato.com, com o MX de send.streamintel.cc apontando para la desde
# 2026-08-09. Antes disso a resposta ia para um gmail pessoal, o que deixava o
# From e o Reply-To em dominios diferentes, coisa que filtro de spam nota.
REPLY_TO = "henrique@send.streamintel.cc"
BROADCAST_UNSUBSCRIBE_TOKEN = "{{{RESEND_UNSUBSCRIBE_URL}}}"
BROADCAST_UNSUBSCRIBE_BLOCK = re.compile(
    r"\s*<p[^>]*>(?:(?!</p>).)*\{\{\{RESEND_UNSUBSCRIBE_URL\}\}\}(?:(?!</p>).)*</p>",
    re.DOTALL,
)
UNSUBSCRIBE_MAILTO = {
    "pt": f"mailto:{REPLY_TO}?subject=sair",
    "en": f"mailto:{REPLY_TO}?subject=unsubscribe",
}
RESEND_BATCH_URL = "https://api.resend.com/emails/batch"
RESEND_MAX_PER_CALL = 100
SECONDS_BETWEEN_CALLS = 1.0  # o Resend aceita 2 req/s; uma por segundo sobra


def read_batch(batch: str) -> list[tuple[str, str]]:
    """Endereco e idioma. Lote antigo nao tem a coluna `language`; ele e
    portugues, que era o unico idioma quando foi montado."""
    path = BATCH_DIR / f"{batch}.csv"
    with path.open(newline="") as handle:
        return [
            (row["email"].strip(), (row.get("language") or DEFAULT_LANGUAGE).strip())
            for row in csv.DictReader(handle)
            if row["email"]
        ]


def body_for_api(html: str) -> str:
    """Tira o paragrafo do descadastro de broadcast. Falha de proposito se o
    marcador sumir do arquivo: seguir em frente mandaria '{{{...}}}' escrito na
    tela de centenas de pessoas."""
    if BROADCAST_UNSUBSCRIBE_TOKEN not in html:
        raise ValueError(f"{BODY_HTML} nao tem o paragrafo de descadastro")
    stripped = BROADCAST_UNSUBSCRIBE_BLOCK.sub("", html)
    if BROADCAST_UNSUBSCRIBE_TOKEN in stripped:
        raise ValueError("o marcador sobrou no corpo depois de limpar")
    return stripped


def build_payloads(
    destinatarios: list[tuple[str, str]], corpos: dict[str, str]
) -> list[dict]:
    return [
        {
            "from": FROM,
            "to": [email],
            "reply_to": REPLY_TO,
            "subject": SUBJECT[idioma],
            "html": corpos[idioma],
            "headers": {"List-Unsubscribe": f"<{UNSUBSCRIBE_MAILTO[idioma]}>"},
        }
        for email, idioma in destinatarios
    ]


def send(api_key: str, payloads: list[dict]) -> None:
    headers = {"Authorization": f"Bearer {api_key}"}
    for start in range(0, len(payloads), RESEND_MAX_PER_CALL):
        chunk = payloads[start : start + RESEND_MAX_PER_CALL]
        response = httpx.post(RESEND_BATCH_URL, headers=headers, json=chunk, timeout=30)
        response.raise_for_status()
        print(f"  enviados {start + len(chunk)}/{len(payloads)}")
        time.sleep(SECONDS_BETWEEN_CALLS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", help="nome do lote, ex: lote-6")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    destinatarios = read_batch(args.batch)
    duplicates = len(destinatarios) - len({e for e, _ in destinatarios})
    if duplicates:
        raise ValueError(f"{args.batch} tem {duplicates} email repetido")
    idiomas = sorted({idioma for _, idioma in destinatarios})
    faltando = [i for i in idiomas if i not in BODY_HTML or not BODY_HTML[i].exists()]
    if faltando:
        raise ValueError(f"sem corpo de email para: {', '.join(faltando)}")
    corpos = {i: body_for_api(BODY_HTML[i].read_text()) for i in idiomas}
    payloads = build_payloads(destinatarios, corpos)
    print(
        f"{args.batch}: {len(destinatarios)} destinatarios | idiomas: {'/'.join(idiomas)}"
    )
    for idioma in idiomas:
        print(f"  {idioma}: {SUBJECT[idioma]}")

    if args.dry_run:
        primeiro, idioma = destinatarios[0]
        print(f"dry-run, ninguem recebeu nada. Primeiro: {primeiro} ({idioma})")
        print(f"  List-Unsubscribe: <{UNSUBSCRIBE_MAILTO[idioma]}>")
        Path("/tmp/preview-email.html").write_text(payloads[0]["html"])
        print("  corpo renderizado em /tmp/preview-email.html")
        return 0

    send(os.environ["RESEND_API_KEY"], payloads)
    print(f"{args.batch} enviado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
