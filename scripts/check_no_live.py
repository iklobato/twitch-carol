"""Diz se algum canal do produto está transmitindo agora.

Existe porque o `worker-capture` reinicia em todo deploy. Ele retoma sozinho
qualquer live marcada como `capturing` (é `restart-safe` por desenho), então o que
se perde é o segmento de áudio em voo: no máximo `AUDIO_SEGMENT_SECONDS` = 10
minutos, mais 2 segundos de chat. Não é a live inteira. Mas 10 minutos do áudio de
alguém ainda é motivo para escolher a hora.

A lista de canais vem do próprio produto, pelo endpoint de admin, para não
envelhecer a cada cadastro novo. O estado de "está no ar" vem da GQL pública da
Twitch, que não precisa das nossas credenciais.

    # pegue o cookie `session` de um navegador logado como admin
    python scripts/check_no_live.py --base-url https://streamintel.cc --session "<cookie>"

Sai com 0 quando ninguém está no ar (pode subir) e 1 quando alguém está.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

TWITCH_GQL = "https://gql.twitch.tv/gql"
# O client id público do site da Twitch. Só lê estado público de transmissão.
TWITCH_PUBLIC_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def channel_logins(base_url: str, session: str) -> list[str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/admin/channels",
        headers={"Cookie": f"session={session}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return [row["login"] for row in json.load(response)]
    except urllib.error.HTTPError as err:
        raise SystemExit(
            f"/api/admin/channels respondeu {err.code}. O cookie precisa ser de um "
            "login na lista de admin, e ele é assinado por FERNET_KEY, então um "
            "cookie de dev não vale em produção."
        ) from None


def live_logins(logins: list[str]) -> list[str]:
    query = (
        "query{"
        + "".join(
            f'c{i}: user(login: "{login}") {{ login stream {{ id }} }}'
            for i, login in enumerate(logins)
        )
        + "}"
    )
    request = urllib.request.Request(
        TWITCH_GQL,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Client-Id": TWITCH_PUBLIC_CLIENT_ID,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)["data"]
    return [node["login"] for node in data.values() if node and node.get("stream")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://streamintel.cc")
    parser.add_argument("--session", required=True, help="valor do cookie `session`")
    args = parser.parse_args()

    logins = channel_logins(args.base_url, args.session)
    if not logins:
        # Zero canais não é "pode subir", é sinal de que a consulta falhou.
        raise SystemExit("nenhum canal retornado: nao da para afirmar que esta livre")
    ao_vivo = live_logins(logins)

    print(f"{len(logins)} canais no produto")
    if ao_vivo:
        print(f"AO VIVO AGORA: {', '.join(ao_vivo)}")
        print("Subir agora custa ate 10 min do audio de cada um desses.")
        return 1
    print("NINGUEM AO VIVO: pode subir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
