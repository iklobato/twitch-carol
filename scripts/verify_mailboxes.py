"""Verifica caixas da fila da campanha por sondagem SMTP RCPT, sem enviar nada, e
tira as que o servidor diz que nao existem.

    python scripts/verify_mailboxes.py [--idioma pt] [--go]

RODA NO mail.iklobato.com: host de nuvem bloqueia a porta 25 de saida. Le a fila
do Key-Value Store do Apify por HTTPS, sonda, e (com --go) grava a fila limpa de
volta. Dry-run por padrao.

Regra de ouro: dropa SO com um nao-existe explicito do servidor (550 com "5.1.1"
/ "does not exist" / "user unknown"). Qualquer duvida (4xx, greylist, timeout,
550 generico) MANTEM: perder um lead bom custa dinheiro, manter um morto o portao
segura. Nunca manda DATA.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent.parent / "twitch" / ".env"
if not ENV.exists():  # rodando de dentro do proprio repo
    ENV = Path.home() / "twitch" / ".env"
KV_STORE = "uvXvn4Kyy4XIL2gAW"
HOSTNAME = "mail.iklobato.com"
REMETENTE = "postmaster@iklobato.com"
NAO_EXISTE = re.compile(
    r"5\.1\.1|does not exist|doesn't exist|no such|user unknown|"
    r"unknown user|mailbox unavailable|recipient not found",
    re.I,
)


def carrega_env() -> dict[str, str]:
    env = {}
    for linha in ENV.read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            env[chave.strip()] = valor.strip().strip('"').strip("'")
    return env


def classifica(codigo: int, mensagem: str = "") -> str:
    """'viva', 'morta' ou 'incerta'. So 'morta' com nao-existe explicito."""
    if codigo in (250, 251, 252):
        return "viva"
    if codigo in (550, 551) and NAO_EXISTE.search(mensagem or ""):
        return "morta"
    return "incerta"


def mx_de(dominio: str) -> str | None:
    """MX de menor prioridade via `dig`. None se o dominio nao publica MX."""
    saida = subprocess.run(
        ["dig", "+short", "mx", dominio], capture_output=True, text=True, timeout=20
    ).stdout
    registros = []
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) == 2 and partes[0].isdigit():
            registros.append((int(partes[0]), partes[1].rstrip(".")))
    return min(registros)[1] if registros else None


def sonda_dominio(
    mx: str,
    enderecos: list[str],
    conectar=smtplib.SMTP,
    pausa: float = 1.0,
) -> dict[str, str]:
    """Sonda um dominio numa conexao so. Se TODO endereco der morto, trata como
    bloqueio do nosso IP (nao lista morta) e mantem todos. Erro de conexao mantem
    todos: na duvida nao dropa."""
    resultado: dict[str, str] = {}
    try:
        servidor = conectar(mx, 25, timeout=20)
    except Exception:
        return {e: "incerta" for e in enderecos}
    try:
        servidor.ehlo(HOSTNAME)
        servidor.mail(REMETENTE)
        for endereco in enderecos:
            try:
                codigo, msg = servidor.rcpt(endereco)
                resultado[endereco] = classifica(
                    codigo, msg.decode() if isinstance(msg, bytes) else str(msg)
                )
            except Exception:
                resultado[endereco] = "incerta"
            time.sleep(pausa)
    finally:
        try:
            servidor.quit()
        except Exception:
            pass
    mortas = [e for e, s in resultado.items() if s == "morta"]
    if len(enderecos) >= 5 and len(mortas) == len(enderecos):
        # Dominio inteiro "morto" cheira a bloqueio do nosso IP, nao a lista morta.
        return {e: "incerta" for e in enderecos}
    return resultado


def email_de(item) -> str:
    return (item[0] if isinstance(item, list) else item).lower()


def idioma_de(item) -> str:
    return item[1] if isinstance(item, list) and len(item) > 1 else "pt"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--idioma", default="pt")
    parser.add_argument("--go", action="store_true", help="grava a fila limpa no KV")
    parser.add_argument("--pausa", type=float, default=1.0)
    args = parser.parse_args()

    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_USER_TOKEN")
    if not token and ENV.exists():
        env = carrega_env()
        token = env.get("APIFY_TOKEN") or env.get("APIFY_USER_TOKEN")
    if not token:
        sys.exit("defina APIFY_TOKEN no ambiente (ou num .env)")
    url = f"https://api.apify.com/v2/key-value-stores/{KV_STORE}/records/fila"
    fila = json.loads(urllib.request.urlopen(f"{url}?token={token}", timeout=60).read())

    alvo = [it for it in fila if idioma_de(it) == args.idioma]
    por_dominio: dict[str, list[str]] = {}
    for item in alvo:
        endereco = email_de(item)
        por_dominio.setdefault(endereco.split("@")[-1], []).append(endereco)
    print(f"idioma {args.idioma}: {len(alvo)} enderecos em {len(por_dominio)} dominios")

    status: dict[str, str] = {}
    resumo = Counter()
    for dominio, enderecos in sorted(por_dominio.items()):
        mx = mx_de(dominio)
        if not mx:
            for endereco in enderecos:
                status[endereco] = "incerta"
            resumo["sem-mx (mantido)"] += len(enderecos)
            continue
        parcial = sonda_dominio(mx, enderecos, pausa=args.pausa)
        status.update(parcial)
        contagem = Counter(parcial.values())
        resumo.update(contagem)
        if contagem["morta"]:
            print(f"  {dominio}: {dict(contagem)}")

    mortas = {e for e, s in status.items() if s == "morta"}
    print(f"\nresumo: {dict(resumo)}")
    print(f"mortas a dropar: {len(mortas)}")

    if not args.go:
        print("\n[DRY-RUN] --go para gravar a fila sem as mortas")
        return 0

    limpa = [it for it in fila if email_de(it) not in mortas]
    corpo = json.dumps(limpa).encode()
    req = urllib.request.Request(
        f"{url}?token={token}",
        data=corpo,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=60)
    print(
        f"gravado. fila: {len(fila)} -> {len(limpa)} (dropadas {len(fila) - len(limpa)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
