"""Entrega de cada lote do convite beta, direto da API do Resend.

    python scripts/campaign_stats.py                # relatorio de todos os lotes
    python scripts/campaign_stats.py --portao lote-9  # libera ou barra o envio

E daqui que sai o portao antes de disparar o proximo lote: bounce duro abaixo de
3% e zero reclamacao de spam no lote anterior. Com `--portao` o script nao imprime
relatorio, ele so decide: sai com 0 se pode enviar, com 1 se nao pode. E o que o
systemd do droplet roda antes de cada disparo agendado.

Bounce duro quer dizer caixa que nao existe. Caixa cheia e falha temporaria voltam
do Resend com o mesmo `last_event: bounced`, e so o tipo em `GET /emails/{id}` as
separa. Contar as duas juntas nao mede reputacao nenhuma: barrou o lote-15 medindo
o lote-14 em 3,1% quando o duro dele era 2,5%.

Abertura nao aparece aqui de proposito: o rastreamento esta desligado no dominio
(pixel de rastreio pesa contra um dominio novo, e o numero vem inflado pelo Gmail
e pelo Apple Mail). Quem responde pela conversao e cadastro no app e resposta no
reply-to, nao abertura.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from send_campaign_batch import BATCH_DIR, read_batch  # noqa: E402

RESEND_EMAILS_URL = "https://api.resend.com/emails"
PAGE_SIZE = 100
BOUNCE_LIMIT = 0.03
# Piso de amostra antes de aplicar a %. Abaixo disso um lote pequeno estoura o
# portao com azar, nao com lista ruim: 3 caixas mortas num lote de 41 dao 7,3% e
# barram tudo, com o bounce duro geral em 1,3%. A 200 enviados, uma caixa morta
# vale 0,5%, entao 3% pede ~6 mortas de verdade. ponytail: 200 e o menor teto
# redondo onde a cauda pt saudavel (lotes 18-21, 450 enviados, 1,3%) abre; suba
# para 300-500 se quiser a media mais estavel, a custo de reagir mais devagar.
MIN_SAMPLE = 200
HARD_BOUNCE = "bounced"
SOFT_BOUNCE = "bounced_temporario"
BAD_EVENTS = (HARD_BOUNCE, "complained")
OUTSIDE = "fora dos lotes"


def fetch_emails(client: httpx.Client) -> list[dict]:
    emails: list[dict] = []
    after = None
    while True:
        params = {"limit": PAGE_SIZE} | ({"after": after} if after else {})
        response = client.get(RESEND_EMAILS_URL, params=params)
        response.raise_for_status()
        page = response.json()
        emails += page["data"]
        if not page.get("has_more") or not page["data"]:
            return emails
        after = page["data"][-1]["id"]


def classify_bounce(client: httpx.Client, email_id: str) -> str:
    """Uma chamada a mais por bounce, nao por email: sao dezenas contra milhares.

    Sem tipo o email conta como duro, que e o lado seguro: barrar atrasa um dia,
    liberar queima o dominio."""
    response = client.get(f"{RESEND_EMAILS_URL}/{email_id}")
    response.raise_for_status()
    tipo = (response.json().get("bounce") or {}).get("type")
    return SOFT_BOUNCE if tipo == "Transient" else HARD_BOUNCE


def trilha_e_numero(name: str) -> tuple[str, int]:
    """`lote-11` e a trilha portugues (historico), `lote-en-3` e a inglesa.

    Trilha separada porque publico novo tem bounce e reclamacao desconhecidos:
    misturado no mesmo lote, o portao mede a media e voce so descobre qual
    populacao machucou o dominio quando ja machucou."""
    partes = name.split("-")
    if len(partes) == 2:
        return "pt", int(partes[1])
    return partes[1], int(partes[2])


def batch_number(name: str) -> int:
    return trilha_e_numero(name)[1]


def load_batches() -> dict[str, set[str]]:
    paths = sorted(
        BATCH_DIR.glob("lote-*.csv"), key=lambda path: batch_number(path.stem)
    )
    return {
        path.stem: {email.lower() for email, _ in read_batch(path.stem)}
        for path in paths
    }


def batch_of(recipient: str, batches: dict[str, set[str]]) -> str:
    return next(
        (name for name, emails in batches.items() if recipient in emails), OUTSIDE
    )


def tally(
    api_key: str,
    batches: dict[str, set[str]],
    client: httpx.Client | None = None,
) -> dict[str, collections.Counter]:
    """`client` existe para o teste injetar um transporte falso; em producao ele
    e criado aqui e fechado no fim."""
    events: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    with client or httpx.Client(headers=headers, timeout=30) as http:
        for email in fetch_emails(http):
            recipient = (email["to"] or [""])[0].lower()
            event = email["last_event"]
            if event == HARD_BOUNCE:
                event = classify_bounce(http, email["id"])
            events[batch_of(recipient, batches)][event] += 1
    return events


def report(
    events: dict[str, collections.Counter], batches: dict[str, set[str]]
) -> None:
    for name in list(batches) + [OUTSIDE]:
        counts = events[name]
        total = sum(counts.values())
        if not total:
            print(f"{name}: nao enviado")
            continue
        bad = {event: counts[event] for event in BAD_EVENTS if counts[event]}
        print(
            f"{name}: {total} enviados | {dict(counts)}"
            + (f" | RUIM: {bad}" if bad else "")
        )
        if name == OUTSIDE:
            continue
        print(f"  bounce {counts['bounced'] / total:.1%} | spam {counts['complained']}")


def previous_batch(name: str, batches: dict[str, set[str]]) -> str | None:
    """O lote imediatamente anterior **da mesma trilha**, tenha ele saido ou nao.

    Nao vale pular para o ultimo que saiu: numa corrente agendada isso deixaria o
    lote-10 disparar na quinta conferindo o lote-7, se o lote-9 tivesse falhado na
    quarta. E nao vale comparar com outra trilha: o primeiro lote em ingles nao
    herda a reputacao construida com brasileiros."""
    trilha, numero = trilha_e_numero(name)
    earlier = [
        other
        for other in batches
        if trilha_e_numero(other)[0] == trilha and batch_number(other) < numero
    ]
    return max(earlier, key=batch_number, default=None)


def janela_recente(
    name: str, events: dict[str, collections.Counter], batches: dict[str, set[str]]
) -> collections.Counter:
    """Soma os lotes JA ENVIADOS da mesma trilha, do mais novo para o mais velho,
    ate juntar MIN_SAMPLE enviados (ou acabarem os lotes). Um lote grande fecha a
    janela sozinho (mede so ele, sensivel a um lote ruim recente); um lote pequeno
    puxa os anteriores ate a amostra ficar de tamanho que a % signifique lista, e
    nao sorte."""
    trilha, numero = trilha_e_numero(name)
    anteriores = sorted(
        (
            outro
            for outro in batches
            if trilha_e_numero(outro)[0] == trilha
            and batch_number(outro) < numero
            and sum(events[outro].values())
        ),
        key=batch_number,
        reverse=True,
    )
    janela: collections.Counter = collections.Counter()
    enviados = 0
    for lote in anteriores:
        janela.update(events[lote])
        enviados += sum(events[lote].values())
        if enviados >= MIN_SAMPLE:
            break
    return janela


def gate(
    name: str, events: dict[str, collections.Counter], batches: dict[str, set[str]]
) -> int:
    """0 libera o envio do lote, 1 barra. Barrar e o padrao em qualquer duvida:
    email que nao saiu se manda depois, email que saiu duas vezes nao volta."""
    if name not in batches:
        print(f"PORTAO BLOQUEADO: {name} nao existe em {BATCH_DIR}")
        return 1
    if sum(events[name].values()):
        print(f"PORTAO BLOQUEADO: {name} ja foi enviado, nao mando de novo")
        return 1

    anterior = previous_batch(name, batches)
    if not anterior:
        # Trilha nova nao tem o que medir. Ela sai, mas pequena: quem segura o
        # risco aqui e o tamanho do primeiro degrau (50), nao o portao.
        if trilha_e_numero(name)[1] == 1:
            print(f"portao OK: {name} abre a trilha, nao ha anterior para medir")
            return 0
        print(f"PORTAO BLOQUEADO: {name} nao tem lote anterior, nada para conferir")
        return 1
    if not sum(events[anterior].values()):
        print(f"PORTAO BLOQUEADO: {anterior} nao foi enviado, nao pulo a fila")
        return 1

    counts = janela_recente(name, events, batches)
    total = sum(counts.values())
    bounced = counts["bounced"] / total
    if bounced >= BOUNCE_LIMIT or counts["complained"]:
        print(
            f"PORTAO BLOQUEADO: janela de {total} enviados com bounce {bounced:.1%} "
            f"e {counts['complained']} spam"
        )
        return 1

    print(
        f"portao OK: janela de {total} enviados com bounce {bounced:.1%}, 0 spam. "
        f"{name} liberado"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--portao", metavar="LOTE", help="decide se o lote pode ser enviado agora"
    )
    args = parser.parse_args()

    batches = load_batches()
    events = tally(os.environ["RESEND_API_KEY"], batches)
    if args.portao:
        return gate(args.portao, events, batches)
    report(events, batches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
