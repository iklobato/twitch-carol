"""Prospecta streamer BR pequeno para o beta: acha o email, a Helix qualifica.

Duas fontes de candidato, uma peneira so. `harvest` le o que o Google indexou
das paginas publicas do Twitch e alcanca quem nao esta transmitindo agora (a
maior parte dos emails mora em painel de doacao, que nenhuma API expoe);
`sweep` lista quem esta ao vivo em portugues neste momento e alcanca quem o
Google nao indexou. Nenhuma das duas sabe o tamanho do canal: quem decide isso
e `qualify`, porque contagem de seguidores so existe na Helix.

O harvest cobra por consulta (proxy de busca da Apify, ~USD 0,0025 cada) e
precisa de APIFY_TOKEN no ambiente. O resto usa as credenciais Twitch do app.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from build_campaign_batches import send_priority

from core.twitch import (
    HELIX_URL,
    app_headers,
    get_channels_by_ids,
    get_follower_count,
    get_users_by_logins,
)

SERP_ENDPOINT = "http://www.google.com/search"
SERP_PROXY = "http://groups-GOOGLE_SERP:{password}@proxy.apify.com:8000"
SERP_RESULTS_PER_PAGE = 20
SERP_TIMEOUT_SECONDS = 90.0
SERP_WORKERS = 8
# O email fica no JSON do snippet, a ate ~400 caracteres depois do link do
# canal. Colar o par pela distancia e o que existe: a pagina nao marca a qual
# resultado cada trecho pertence.
SERP_PAIR_WINDOW = 400
USER_AGENT = "Mozilla/5.0"

CANDIDATES_PATH = Path("data/campaign/candidates.csv")
LEADS_PATH = Path("data/campaign/leads.csv")
CAMPAIGN_DIR = Path("data/campaign")
SENT_BATCH_GLOB = "lote-*.csv"

# Dominio remetente novo: 5 dias subindo devagar, com portao entre um dia e o
# outro. Somam os 521 leads da primeira colheita.
RAMP_SIZES = (50, 80, 120, 150, 121)

MAX_FOLLOWERS = 5_000
MIN_FOLLOWERS = 100
TARGET_LANGUAGE = "pt"
PARTNER_TYPE = "partner"
HELIX_SLEEP_SECONDS = 0.15
STREAMS_PAGE_SIZE = 100

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CHANNEL_PATTERN = re.compile(r"twitch\.tv/([A-Za-z0-9_]{3,25})")
# `%` so aparece quando o casamento veio da propria query na URL da busca; as
# extensoes sao imagem de avatar servida de um dominio com cara de email.
EMAIL_REJECT = ("%", "@2x", "@3x")
EMAIL_REJECT_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
)
NOT_A_CHANNEL = frozenset(
    {"videos", "directory", "settings", "downloads", "prime", "subs", "turbo", "jobs"}
)


def _clean_email(raw: str) -> str:
    address = raw.lower().strip(".,;:)")
    if any(bad in address for bad in EMAIL_REJECT):
        return ""
    if address.endswith(EMAIL_REJECT_SUFFIXES):
        return ""
    return address


def _serp_proxy_url(apify_token: str) -> str:
    """A senha do proxy vive na conta Apify, nao no .env."""
    response = httpx.get(
        "https://api.apify.com/v2/users/me",
        params={"token": apify_token},
        timeout=SERP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return SERP_PROXY.format(password=response.json()["data"]["proxy"]["password"])


def fetch_serp(query: str, start: int, proxy_url: str) -> str:
    params = {"q": query, "num": str(SERP_RESULTS_PER_PAGE), "start": str(start)}
    url = f"{SERP_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with httpx.Client(proxy=proxy_url, timeout=SERP_TIMEOUT_SECONDS) as http:
        response = http.get(url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def extract_pairs(page: str) -> list[tuple[str, str]]:
    """Casa cada email com o canal citado logo antes dele na mesma pagina."""
    channels = [(m.start(), m.group(1).lower()) for m in CHANNEL_PATTERN.finditer(page)]
    pairs = []
    for match in EMAIL_PATTERN.finditer(page):
        address = _clean_email(match.group(0))
        if not address:
            continue
        before = [
            login
            for pos, login in channels
            if 0 <= match.start() - pos <= SERP_PAIR_WINDOW
        ]
        if not before or before[-1] in NOT_A_CHANNEL:
            continue
        pairs.append((before[-1], address))
    return pairs


def _harvest_query(
    keyword: str, domain: str, pages: int, proxy_url: str
) -> list[tuple[str, str]]:
    """Uma consulta ate acabar o que o Google tem: pagina sem par nenhum quer
    dizer que as seguintes tambem nao terao."""
    query = f'site:twitch.tv "{keyword}" "{domain}"'
    pairs: list[tuple[str, str]] = []
    for page in range(pages):
        found = extract_pairs(
            fetch_serp(query, page * SERP_RESULTS_PER_PAGE, proxy_url)
        )
        pairs.extend(found)
        if not found:
            break
    return pairs


def harvest(
    keywords: list[str], domains: list[str], pages: int
) -> list[dict[str, str]]:
    """Em paralelo porque o proxy de busca estrangula conexao reusada: a mesma
    consulta cai de 3s para 37s quando repetida no mesmo cliente."""
    proxy_url = _serp_proxy_url(os.environ["APIFY_TOKEN"])
    found: dict[tuple[str, str], dict[str, str]] = {}
    combos = [(keyword, domain) for keyword in keywords for domain in domains]
    with ThreadPoolExecutor(max_workers=SERP_WORKERS) as pool:
        running = {
            pool.submit(_harvest_query, keyword, domain, pages, proxy_url): keyword
            for keyword, domain in combos
        }
        for done, future in enumerate(as_completed(running), start=1):
            keyword = running[future]
            try:
                pairs = future.result()
            except httpx.HTTPError as error:
                print(
                    f"  [{done}/{len(combos)}] '{keyword}' falhou: {error}", flush=True
                )
                continue
            fresh = [pair for pair in pairs if pair not in found]
            for login, address in fresh:
                found[login, address] = {
                    "source": "serp",
                    "login": login,
                    "email": address,
                    "hint": keyword,
                }
            print(
                f"  [{done}/{len(combos)}] '{keyword}': {len(pairs)} pares, "
                f"{len(fresh)} novos, {len(found)} no total",
                flush=True,
            )
    return list(found.values())


def sweep(pages: int) -> list[dict[str, str]]:
    """Quem esta ao vivo em portugues agora. Sem email ainda: vem da bio no
    qualify."""
    candidates: dict[str, dict[str, str]] = {}
    cursor = ""
    with httpx.Client(timeout=SERP_TIMEOUT_SECONDS) as http:
        for page in range(pages):
            params = {"language": TARGET_LANGUAGE, "first": str(STREAMS_PAGE_SIZE)}
            if cursor:
                params["after"] = cursor
            response = http.get(
                f"{HELIX_URL}/streams", params=params, headers=app_headers(http)
            )
            response.raise_for_status()
            body = response.json()
            for row in body.get("data", []):
                login = row["user_login"].lower()
                candidates[login] = {
                    "source": "live",
                    "login": login,
                    "email": "",
                    "hint": row.get("game_name", ""),
                }
            cursor = body.get("pagination", {}).get("cursor", "")
            print(f"  streams p{page + 1}: {len(candidates)} canais acumulados")
            if not cursor:
                break
    return list(candidates.values())


def already_contacted(campaign_dir: Path) -> set[str]:
    """Enderecos que ja entraram em lote. `emails_extracted.txt` nao conta: e
    fonte, nao historico de envio."""
    sent: set[str] = set()
    for path in sorted(campaign_dir.glob(SENT_BATCH_GLOB)):
        with path.open(newline="") as handle:
            sent.update(
                row["email"].strip().lower()
                for row in csv.DictReader(handle)
                if row.get("email")
            )
    return sent


def deliverable_domains(addresses: list[str], client: httpx.Client) -> set[str]:
    """Dominio sem MX e bounce garantido, e bounce cedo queima o remetente. Sao
    poucos dominios distintos, entao uma consulta DNS por dominio resolve. Pega
    tanto piada de bio (hehe.com) quanto endereco colado errado no scraping
    (gmail.comeste)."""
    good = set()
    for domain in {address.rpartition("@")[2] for address in addresses}:
        response = client.get(
            "https://dns.google/resolve", params={"name": domain, "type": "MX"}
        )
        if response.json().get("Answer"):
            good.add(domain)
            continue
        print(f"  descartado, dominio sem MX: {domain}")
    return good


def _email_of(candidate: dict[str, str], description: str) -> str:
    if candidate["email"]:
        return candidate["email"]
    found = [_clean_email(m) for m in EMAIL_PATTERN.findall(description)]
    return next((address for address in found if address), "")


def qualify(candidates: list[dict[str, str]], sent: set[str]) -> list[dict[str, str]]:
    # O mesmo canal pode vir das duas fontes; a linha do SERP ganha, porque ela
    # traz o email do painel, que a bio da Helix nao tem.
    by_login: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        known = by_login.get(candidate["login"])
        if not (known and known["email"]):
            by_login[candidate["login"]] = candidate

    profiles = get_users_by_logins(list(by_login))
    print(f"perfis existentes na Twitch: {len(profiles)}/{len(by_login)}")

    with_email = [
        (profile, _email_of(by_login[profile.login.lower()], profile.description))
        for profile in profiles
        if profile.login.lower() in by_login
    ]
    with_email = [
        (profile, address)
        for profile, address in with_email
        if address and address not in sent and profile.broadcaster_type != PARTNER_TYPE
    ]
    print(f"com email, nao contatados, nao partner: {len(with_email)}")

    languages = {
        info.broadcaster_id: info
        for info in get_channels_by_ids([int(p.id) for p, _ in with_email])
    }
    in_portuguese = [
        (profile, address)
        for profile, address in with_email
        if languages.get(profile.id)
        and languages[profile.id].broadcaster_language == TARGET_LANGUAGE
    ]
    print(f"canal em portugues: {len(in_portuguese)}")

    with httpx.Client(timeout=SERP_TIMEOUT_SECONDS) as dns:
        good_domains = deliverable_domains([a for _, a in in_portuguese], dns)
    reachable = [
        (profile, address)
        for profile, address in in_portuguese
        if address.rpartition("@")[2] in good_domains
    ]
    print(f"dominio de email entregavel: {len(reachable)}")

    leads = []
    for profile, address in reachable:
        followers = get_follower_count(int(profile.id))
        time.sleep(HELIX_SLEEP_SECONDS)
        if not MIN_FOLLOWERS <= followers < MAX_FOLLOWERS:
            continue
        leads.append(
            {
                "login": profile.login,
                "email": address,
                "followers": str(followers),
                "broadcaster_type": profile.broadcaster_type or "none",
                "game": languages[profile.id].game_name,
                "created_at": profile.created_at.date().isoformat(),
                "source": by_login[profile.login.lower()]["source"],
            }
        )
    return sorted(leads, key=lambda lead: int(lead["followers"]), reverse=True)


def split_ramp(leads: list[dict[str, str]], first_number: int) -> list[Path]:
    """Rampa de aquecimento: o dominio remetente tem historico curto, entao o
    volume sobe aos poucos. Dentro de cada lote vale a mesma ordem que o
    build_campaign_batches ja usa (contato de negocio primeiro, Microsoft por
    ultimo), por isso a funcao vem de la em vez de ser copiada."""
    ordered = sorted(leads, key=lambda lead: send_priority(lead["email"]))
    paths, start = [], 0
    for offset, size in enumerate(RAMP_SIZES):
        chunk = ordered[start : start + size]
        if not chunk:
            break
        path = CAMPAIGN_DIR / f"lote-{first_number + offset}.csv"
        if path.exists():
            raise FileExistsError(
                f"{path} ja existe; nao vou sobrescrever lote enviado"
            )
        write_rows(path, [{"email": lead["email"]} for lead in chunk], ["email"])
        paths.append(path)
        start += size
    leftover = len(ordered) - start
    if leftover:
        print(f"aviso: {leftover} leads sobraram fora da rampa")
    return paths


def write_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def merge_candidates(
    existing: list[dict[str, str]], new: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged = {(row["login"], row["email"]): row for row in existing}
    merged.update({(row["login"], row["email"]): row for row in new})
    return list(merged.values())


CANDIDATE_FIELDS = ["source", "login", "email", "hint"]
LEAD_FIELDS = [
    "login",
    "email",
    "followers",
    "broadcaster_type",
    "game",
    "created_at",
    "source",
]

KEYWORDS = [
    "live todos os dias",
    "lives diárias",
    "todo dia tem live",
    "pix do canal",
    "chave pix",
    "apoie o canal",
    "doação",
    "ajude o canal",
    "meta de subs",
    "meta de seguidores",
    "rumo ao afiliado",
    "rumo a parceiro",
    "contato profissional",
    "contato comercial",
    "parcerias",
    "contato para parcerias",
    "streamer iniciante",
    "canal novo",
    "sou streamer",
    "streamer brasileiro",
    "horários das lives",
    "cronograma de lives",
    "programação da semana",
    "jogos e zueira",
    "canal de variedades",
    "gameplays em português",
    "vtuber br",
    "vtuber brasileira",
    "gta rp",
    "valorant br",
    "minecraft br",
    # Segunda onda: palavra comum rende mais que frase exata, porque o filtro de
    # verdade e o dominio na query, e a palavra so troca quais paginas aparecem.
    "contato",
    "email para contato",
    "fale comigo",
    "para contato",
    "publicidade",
    "assessoria",
    "imprensa",
    "propostas",
    "orçamento",
    "trabalhe comigo",
    "faça uma doação",
    "doações",
    "apoiar o canal",
    "me apoie",
    "apoio",
    "pix para doação",
    "doe qualquer valor",
    "ajude com um pix",
    "vaquinha",
    "contribuição",
    "meta do mês",
    "bora crescer",
    "crescer juntos",
    "ajude o canal a crescer",
    "rumo aos 1000",
    "rumo aos 100 seguidores",
    "obrigado por seguir",
    "meta de bits",
    "objetivo do canal",
    "novo seguidor",
    "toda segunda",
    "toda terça",
    "toda quarta",
    "toda quinta",
    "toda sexta",
    "horário de brasília",
    "lives à noite",
    "às 20h",
    "brasileiro",
    "brasileira",
    "do brasil",
    "canal brasileiro",
    "sou do brasil",
    "nordestino",
    "carioca",
    "mineiro",
    "gameplay",
    "jogatina",
    "zueira",
    "roleplay",
    "cidade alta",
    "speedrun",
    "just chatting",
    "conversa e jogos",
    "jogos variados",
    "competitivo",
    "comunidade",
    "entre no discord",
    "redes sociais",
    "me siga",
]
DOMAINS = ["@gmail.com", "@hotmail.com", "@outlook.com", "@live.com"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serp = sub.add_parser("harvest", help="busca no Google via proxy pago")
    serp.add_argument("--pages", type=int, default=3)
    serp.add_argument("--keywords", type=int, default=len(KEYWORDS))
    serp.add_argument("--domains", type=int, default=len(DOMAINS))
    # Cada consulta e paga: pular as palavras ja coletadas evita pagar de novo
    # por resultado que o dedup ia descartar.
    serp.add_argument("--skip", type=int, default=0)

    live = sub.add_parser("sweep", help="quem esta ao vivo em portugues agora")
    live.add_argument("--pages", type=int, default=120)

    sub.add_parser("qualify", help="enriquece na Helix e filtra")
    sub.add_parser("self-check", help="testa o extrator sem rede")

    split = sub.add_parser("batches", help="divide os leads nos lotes da rampa")
    split.add_argument("--start", type=int, default=6, help="numero do primeiro lote")

    args = parser.parse_args()
    if args.command == "self-check":
        _self_check()
        return

    if args.command == "batches":
        for path in split_ramp(read_rows(LEADS_PATH), args.start):
            print(f"{path}: {sum(1 for _ in path.open()) - 1} emails")
        return

    commands = {
        "harvest": lambda: harvest(
            KEYWORDS[args.skip : args.skip + args.keywords],
            DOMAINS[: args.domains],
            args.pages,
        ),
        "sweep": lambda: sweep(args.pages),
    }
    if args.command in commands:
        # A coleta demora minutos: so ler o arquivo depois dela evita apagar o
        # que outra coleta escreveu nesse meio tempo.
        collected = commands[args.command]()
        existing = read_rows(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else []
        rows = merge_candidates(existing, collected)
        write_rows(CANDIDATES_PATH, rows, CANDIDATE_FIELDS)
        print(
            f"{CANDIDATES_PATH}: {len(rows)} candidatos ({len(rows) - len(existing)} novos)"
        )
        return

    leads = qualify(read_rows(CANDIDATES_PATH), already_contacted(CAMPAIGN_DIR))
    write_rows(LEADS_PATH, leads, LEAD_FIELDS)
    print(f"{LEADS_PATH}: {len(leads)} leads qualificados")


def _self_check() -> None:
    page = (
        'x"https://www.twitch.tv/canalpequeno/about","Sobre","contato@gmail.com fala"'
        'y"https://www.twitch.tv/outro/videos","V","https://cdn.tv/a@2x.png"'
    )
    assert extract_pairs(page) == [
        ("canalpequeno", "contato@gmail.com")
    ], extract_pairs(page)
    assert _clean_email("A@Gmail.com.") == "a@gmail.com"
    assert _clean_email("logo@2x.png") == ""
    far = 'https://www.twitch.tv/longe/about"' + "z" * 500 + '"tarde@gmail.com"'
    assert extract_pairs(far) == []
    print("self-check ok")


if __name__ == "__main__":
    main()
