"""Calls the running followers endpoint once per demo channel and checks what came
back, so each state is validated against the API's real answer.

Expects `scripts.seed_demo_followers` to have run against the same database and the
API to be listening on API_URL with the same FERNET_KEY.

    DATABASE_URL=... FERNET_KEY=... python -m scripts.validate_demo_followers
"""

import json
import os
import sys
import urllib.error
import urllib.request

from sqlalchemy import select

from core.crypto import create_session_token
from core.db import session_factory
from core.models import Channel

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8011")
DEMOS = ("demo_grande", "demo_comprado", "demo_pequeno", "demo_token")

# What each demo channel is supposed to prove, so a wrong answer fails loudly
# instead of being read past. (needs_reconnect, base is concentrated)
EXPECTED = {
    "demo_grande": (False, False),
    "demo_comprado": (False, True),
    "demo_pequeno": (False, False),
    "demo_token": (True, False),
}
MAX_SEGMENT_MEMBERS = 100


def fetch(login: str, token: str) -> tuple[int, dict, int]:
    request = urllib.request.Request(
        f"{API_URL}/api/followers", headers={"Cookie": f"session={token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw), len(raw)
    except urllib.error.HTTPError as err:
        return err.code, {"detail": err.read().decode()[:120]}, 0


def main() -> int:
    factory = session_factory()
    ok = True
    print(
        f"{'canal':16}{'http':>6}{'total':>8}{'membros':>9}{'KB':>7}"
        f"{'reconect':>10}{'comprada':>10}  detalhe"
    )
    with factory() as db:
        for login in DEMOS:
            channel_id = db.scalar(select(Channel.id).where(Channel.login == login))
            if channel_id is None:
                print(f"{login:16}  nao semeado")
                ok = False
                continue
            status, body, size = fetch(login, create_session_token(channel_id))
            if status != 200:
                print(f"{login:16}{status:>6}  {body.get('detail', '')}")
                ok = False
                continue

            members = sum(len(s["members"]) for s in body["ai"]["segments"])
            base = body["signals"]["base_age"]
            reconnect = body["needs_reconnect"]
            biggest = max(
                (len(s["members"]) for s in body["ai"]["segments"]), default=0
            )
            expected_reconnect, expected_concentrated = EXPECTED[login]
            problems = []
            if reconnect is not expected_reconnect:
                problems.append(f"reconnect esperado {expected_reconnect}")
            if base["is_concentrated"] is not expected_concentrated:
                problems.append(f"comprada esperado {expected_concentrated}")
            if biggest > MAX_SEGMENT_MEMBERS:
                problems.append(f"segmento com {biggest} membros, acima do teto")
            if problems:
                ok = False

            print(
                f"{login:16}{status:>6}{body['kpis']['total']:>8}{members:>9}"
                f"{size // 1024:>7}{str(reconnect):>10}"
                f"{str(base['is_concentrated']):>10}  "
                f"janela={base['window_share']} meses={base['months_spanned']}"
                + (("  FALHOU: " + "; ".join(problems)) if problems else "")
            )
    print()
    print("TUDO COMO ESPERADO" if ok else "ALGO SAIU DIFERENTE DO ESPERADO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
