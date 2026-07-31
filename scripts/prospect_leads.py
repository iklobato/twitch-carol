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
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
from build_campaign_batches import send_priority

from core.twitch import (
    HELIX_URL,
    TwitchAuthError,
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
# Diario de bordo da coleta. Cada consulta ao Google custa dinheiro, e o
# `candidates.csv` so era escrito no fim: um erro depois de 2.000 buscas jogava
# ~USD 5 no lixo. Agora o resultado vai para ca conforme chega, e o arquivo e
# consumido e apagado quando a coleta fecha. Se sobrar, a proxima coleta o recolhe.
JOURNAL_PATH = Path("data/campaign/coleta-parcial.csv")
# Contagem de seguidores e a etapa mais lenta (uma chamada por canal, com pausa).
# Guardar o numero evita repetir 6.000 chamadas quando algo falha no meio, e faz
# a qualificacao diaria custar so os canais novos.
FOLLOWERS_CACHE_PATH = Path("data/campaign/seguidores.csv")
FOLLOWERS_CACHE_DAYS = 7
# Quem ja foi perguntado ao Google, com ou sem resultado. Sem esse registro a
# colheita por login pagaria de novo, todo dia, por quem nao tem email publico.
LOGINS_TRIED_PATH = Path("data/campaign/logins-tentados.csv")
# Pedaco minimo do login que precisa aparecer no endereco, e o maximo de
# enderecos que um login pode casar antes de virar suspeito. A pagina de busca
# traz email de outras pessoas junto, e convite para a pessoa errada nao vira
# bounce, vira reclamacao de spam, que e o unico numero fatal para o dominio.
LOGIN_MATCH_CHARS = 6
LOGIN_MAX_MATCHES = 2
# Palavra que o streamer gruda no proprio nome para fazer o email de negocio.
# E o que separa `contatothimagro` (o streamer) de `johanna.facada` (outra
# pessoa que so tem o mesmo sobrenome).
PALAVRAS_DE_NEGOCIO = (
    "contato",
    "contact",
    "contacto",
    "business",
    "comercial",
    "parcerias",
    "equipe",
    "empresa",
    "oficial",
    "adm",
    "pro",
)
LEADS_PATH = Path("data/campaign/leads.csv")
CAMPAIGN_DIR = Path("data/campaign")
SENT_BATCH_GLOB = "lote-*.csv"

# Continuacao da rampa. A primeira leva subiu 50, 80, 120, 150, 121 e fechou os
# 521 leads iniciais sem nenhuma reclamacao de spam, entao o proximo passo parte
# de onde ela parou, e nao do comeco. Cada degrau ainda passa pelo portao, que
# ja barrou um envio quando o bounce chegou a 3,3%.
RAMP_SIZES = (200, 250, 300, 350, 400)

TARGET_LANGUAGE = "pt"
# Coletar em ingles e de graca (o sweep e Helix), mas mandar o convite em
# portugues para canal em ingles rende reclamacao de spam, que e o unico
# numero que o portao trata como fatal. Por isso a coleta aceita varios
# idiomas e o `qualify` marca o idioma em cada lead: quem envia decide.
IDIOMAS_COLETA = ("pt", "en")
PARTNER_TYPE = "partner"
DNS_RETRIES = 3
DNS_BACKOFF_SECONDS = 1.0
HELIX_RETRIES = 3
HELIX_BACKOFF_SECONDS = 2.0


@dataclass(frozen=True)
class Publico:
    """Quem a colheita procura. A primeira leva (100 a 5.000 seguidores, sem
    partner) esgotou: sobraram no disco 249 canais acima de 5.000, que sao o
    perfil com dinheiro para assinar. Por isso a faixa virou parametro."""

    min_seguidores: int = 5_000
    max_seguidores: int = 100_000
    inclui_partner: bool = True

    def cabe(self, seguidores: int, broadcaster_type: str | None) -> bool:
        if not self.inclui_partner and broadcaster_type == PARTNER_TYPE:
            return False
        return self.min_seguidores <= seguidores < self.max_seguidores


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
    keyword: str, domain: str, pages: int, proxy_url: str, first_page: int = 0
) -> list[tuple[str, str]]:
    """Uma consulta ate acabar o que o Google tem: pagina sem par nenhum quer
    dizer que as seguintes tambem nao terao. `first_page` pula a profundidade ja
    comprada numa colheita anterior, porque cada pagina e cobrada de novo."""
    query = f'site:twitch.tv "{keyword}" "{domain}"'
    pairs: list[tuple[str, str]] = []
    for page in range(first_page, pages):
        found = extract_pairs(
            fetch_serp(query, page * SERP_RESULTS_PER_PAGE, proxy_url)
        )
        pairs.extend(found)
        if not found:
            break
    return pairs


def anota_no_diario(linhas: list[dict[str, str]]) -> None:
    """Grava agora o que a busca acabou de trazer, sem esperar o fim."""
    if not linhas:
        return
    novo = not JOURNAL_PATH.exists()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=CANDIDATE_FIELDS)
        if novo:
            escritor.writeheader()
        escritor.writerows(linhas)


def recolhe_diario() -> list[dict[str, str]]:
    """O que uma coleta anterior deixou pela metade."""
    if not JOURNAL_PATH.exists():
        return []
    resgatado = read_rows(JOURNAL_PATH)
    if resgatado:
        print(f"  recuperados {len(resgatado)} pares de uma coleta interrompida")
    return resgatado


def _e_do_streamer(login: str, endereco: str) -> bool:
    """O login aparece no endereco, e o que sobra e enfeite de negocio.

    Medido em 60 logins reais (2026-07-30): so exigir que o login apareça em
    qualquer lugar aceita `kosky` -> `derek.kosky@gmail.com` e `facada` ->
    `johanna.facada@gmail.com`, que sao pessoas com o mesmo sobrenome, e
    `coreano` -> `profesordecoreano@gmail.com`, que e a palavra solta. Exigir que
    o resto seja vazio ou palavra de negocio derruba os tres."""
    local = re.sub(r"[._+-]", "", endereco.split("@")[0].lower())
    alvo = re.sub(r"[._+-]", "", login.lower())
    pedaco = alvo if alvo in local else alvo[:LOGIN_MATCH_CHARS]
    if pedaco not in local:
        return False
    posicao = local.find(pedaco)
    sobra = (local[:posicao], local[posicao + len(pedaco) :])
    return all(
        not parte or any(p in parte for p in PALAVRAS_DE_NEGOCIO) for parte in sobra
    )


def email_do_login(login: str, pagina: str) -> list[str]:
    """Enderecos da pagina que pertencem a este login.

    Login que casa com muitos enderecos e palavra comum ou sobrenome, e ai
    nenhum deles e confiavel: descarta todos em vez de escolher no chute."""
    achados = []
    for encontrado in EMAIL_PATTERN.finditer(pagina):
        endereco = _clean_email(encontrado.group(0))
        if endereco and _e_do_streamer(login, endereco):
            achados.append(endereco)
    unicos = sorted(set(achados))
    return unicos if len(unicos) <= LOGIN_MAX_MATCHES else []


def logins_ja_tentados() -> set[str]:
    if not LOGINS_TRIED_PATH.exists():
        return set()
    return {linha["login"] for linha in read_rows(LOGINS_TRIED_PATH)}


def anota_login_tentado(logins: list[str], hoje: date) -> None:
    novo = not LOGINS_TRIED_PATH.exists()
    LOGINS_TRIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOGINS_TRIED_PATH.open("a", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=["login", "data"])
        if novo:
            escritor.writeheader()
        escritor.writerows({"login": lg, "data": hoje.isoformat()} for lg in logins)


def _harvest_login(login: str, domain: str, proxy_url: str) -> list[str]:
    return email_do_login(login, fetch_serp(f'"{login}" "{domain}"', 0, proxy_url))


def logins_sem_email(limite: int) -> list[str]:
    """Quem o sweep encontrou ao vivo, nunca teve email achado, e ainda nao foi
    perguntado ao Google. Em 2026-07-30 eram 30.267 logins, 99% deles canal em
    portugues, que e o unico bolso grande que sobrou."""
    com_email, candidatos = set(), []
    for linha in read_rows(CANDIDATES_PATH):
        if linha.get("email"):
            com_email.add(linha["login"])
    ja_tentados = logins_ja_tentados()
    vistos = set()
    for linha in read_rows(CANDIDATES_PATH):
        login = linha["login"]
        if login in com_email or login in ja_tentados or login in vistos:
            continue
        vistos.add(login)
        candidatos.append(login)
    print(
        f"logins sem email e nunca perguntados: {len(candidatos)}; "
        f"vou tentar {min(limite, len(candidatos))}"
    )
    return candidatos[:limite]


def harvest_logins(logins: list[str], domains: list[str]) -> list[dict[str, str]]:
    """Pergunta ao Google pelo email de cada streamer que voce ja conhece pelo
    login, em vez de procurar gente nova por frase.

    Medido em 2026-07-30 com 200 logins do sweep: 96% das paginas trazem algum
    email e 62% trazem um que casa com o login, contra 4% da varredura em
    profundidade. O bolso e grande (30 mil logins sem email, 99% deles em
    portugues) e ja e brasileiro, que e onde o funil de idioma nao mata."""
    proxy_url = _serp_proxy_url(os.environ["APIFY_TOKEN"])
    encontrados: dict[tuple[str, str], dict[str, str]] = {}
    combos = [(login, domain) for login in logins for domain in domains]
    with ThreadPoolExecutor(max_workers=SERP_WORKERS) as pool:
        rodando = {
            pool.submit(_harvest_login, login, domain, proxy_url): login
            for login, domain in combos
        }
        for feitas, futuro in enumerate(as_completed(rodando), start=1):
            login = rodando[futuro]
            try:
                enderecos = futuro.result()
            except httpx.HTTPError as erro:
                print(f"  [{feitas}/{len(combos)}] '{login}' falhou: {erro}", flush=True)
                continue
            novos = [
                {"source": "serp-login", "login": login, "email": e, "hint": "busca por login"}
                for e in enderecos
                if (login, e) not in encontrados
            ]
            for linha in novos:
                encontrados[login, linha["email"]] = linha
            anota_no_diario(novos)
            if feitas % 25 == 0 or novos:
                print(
                    f"  [{feitas}/{len(combos)}] '{login}': {len(novos)} novos, "
                    f"{len(encontrados)} no total",
                    flush=True,
                )
    anota_login_tentado(sorted({lg for lg, _ in combos}), date.today())
    return list(encontrados.values())


def harvest(
    keywords: list[str], domains: list[str], pages: int, first_page: int = 0
) -> list[dict[str, str]]:
    """Em paralelo porque o proxy de busca estrangula conexao reusada: a mesma
    consulta cai de 3s para 37s quando repetida no mesmo cliente."""
    proxy_url = _serp_proxy_url(os.environ["APIFY_TOKEN"])
    found: dict[tuple[str, str], dict[str, str]] = {}
    combos = [(keyword, domain) for keyword in keywords for domain in domains]
    with ThreadPoolExecutor(max_workers=SERP_WORKERS) as pool:
        running = {
            pool.submit(
                _harvest_query, keyword, domain, pages, proxy_url, first_page
            ): keyword
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
            linhas = [
                {"source": "serp", "login": login, "email": address, "hint": keyword}
                for login, address in fresh
            ]
            for (login, address), linha in zip(fresh, linhas, strict=True):
                found[login, address] = linha
            anota_no_diario(linhas)
            print(
                f"  [{done}/{len(combos)}] '{keyword}': {len(pairs)} pares, "
                f"{len(fresh)} novos, {len(found)} no total",
                flush=True,
            )
    return list(found.values())


def sweep(pages: int, idiomas: tuple[str, ...] = IDIOMAS_COLETA) -> list[dict[str, str]]:
    """Quem esta ao vivo agora, um idioma por vez. Sem email ainda: vem da bio no
    qualify. `pages` e o teto por idioma, e a Helix corta sozinha quando acabam os
    canais (em portugues isso acontece perto da pagina 31)."""
    candidates: dict[str, dict[str, str]] = {}
    with httpx.Client(timeout=SERP_TIMEOUT_SECONDS) as http:
        for idioma in idiomas:
            antes, cursor = len(candidates), ""
            for page in range(pages):
                params = {"language": idioma, "first": str(STREAMS_PAGE_SIZE)}
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
                print(f"  {idioma} p{page + 1}: {len(candidates)} canais acumulados")
                if not cursor:
                    break
            print(f"  {idioma}: {len(candidates) - antes} canais")
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
    good, indefinidos = set(), []
    for domain in {address.rpartition("@")[2] for address in addresses}:
        answer = _mx_answer(domain, client)
        if answer is None:
            indefinidos.append(domain)
            continue
        if answer:
            good.add(domain)
            continue
        print(f"  descartado, dominio sem MX: {domain}")
    if indefinidos:
        # Ficar de fora e o lado seguro: dominio sem MX e bounce garantido, e
        # bounce queima o remetente. Mas some lead, entao tem que aparecer.
        print(f"  {len(indefinidos)} dominios sem resposta do DNS, ficaram de fora")
    return good


def _mx_answer(domain: str, client: httpx.Client) -> list | None:
    """Registros MX do dominio, [] se nao tem, None se o DNS nao respondeu.
    O resolvedor limita requisicao e devolve pagina de erro em vez de JSON
    quando a lista e grande, por isso a espera crescente entre as tentativas."""
    for tentativa in range(DNS_RETRIES):
        try:
            response = client.get(
                "https://dns.google/resolve", params={"name": domain, "type": "MX"}
            )
            response.raise_for_status()
            return response.json().get("Answer", [])
        except (httpx.HTTPError, ValueError):
            time.sleep(DNS_BACKOFF_SECONDS * (tentativa + 1))
    return None


def _email_of(candidate: dict[str, str], description: str) -> str:
    if candidate["email"]:
        return candidate["email"]
    found = [_clean_email(m) for m in EMAIL_PATTERN.findall(description)]
    return next((address for address in found if address), "")


def le_cache_seguidores(hoje: date) -> dict[str, int]:
    """Contagens ainda frescas. Fora do prazo elas voltam a ser consultadas,
    porque canal cresce e a faixa de seguidores e o filtro que decide o lead."""
    if not FOLLOWERS_CACHE_PATH.exists():
        return {}
    limite = hoje - timedelta(days=FOLLOWERS_CACHE_DAYS)
    frescas = {}
    for linha in read_rows(FOLLOWERS_CACHE_PATH):
        try:
            if date.fromisoformat(linha["data"]) >= limite:
                frescas[linha["login"]] = int(linha["followers"])
        except (ValueError, KeyError):
            continue
    return frescas


def anota_seguidores(login: str, followers: int, hoje: date) -> None:
    novo = not FOLLOWERS_CACHE_PATH.exists()
    FOLLOWERS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FOLLOWERS_CACHE_PATH.open("a", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=["login", "followers", "data"])
        if novo:
            escritor.writeheader()
        escritor.writerow(
            {"login": login, "followers": followers, "data": hoje.isoformat()}
        )


def _seguidores(
    profile_id: int, buscar=get_follower_count, esperar=time.sleep
) -> int | None:
    """Contagem de seguidores tolerante, ou None se a Twitch nao respondeu.

    Numa varredura de milhares de canais um 500 da Twitch e certeza estatistica:
    aconteceu duas vezes em 2026-07-29. Derrubar a colheita inteira por causa de
    um canal e o pior desfecho possivel, porque leva embora os 15 minutos de
    chamadas que ja foram feitas."""
    for tentativa in range(HELIX_RETRIES):
        try:
            return buscar(profile_id)
        except (TwitchAuthError, httpx.HTTPError):
            esperar(HELIX_BACKOFF_SECONDS * (tentativa + 1))
    return None


def qualify(
    candidates: list[dict[str, str]],
    sent: set[str],
    publico: Publico,
    idiomas: tuple[str, ...] = (TARGET_LANGUAGE,),
) -> list[dict[str, str]]:
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
        if address
        and address not in sent
        and (publico.inclui_partner or profile.broadcaster_type != PARTNER_TYPE)
    ]
    print(f"com email e nao contatados: {len(with_email)}")

    languages = {
        info.broadcaster_id: info
        for info in get_channels_by_ids([int(p.id) for p, _ in with_email])
    }
    in_portuguese = [
        (profile, address)
        for profile, address in with_email
        if languages.get(profile.id)
        and languages[profile.id].broadcaster_language in idiomas
    ]
    print(f"canal em {'/'.join(idiomas)}: {len(in_portuguese)}")

    with httpx.Client(timeout=SERP_TIMEOUT_SECONDS) as dns:
        good_domains = deliverable_domains([a for _, a in in_portuguese], dns)
    reachable = [
        (profile, address)
        for profile, address in in_portuguese
        if address.rpartition("@")[2] in good_domains
    ]
    print(f"dominio de email entregavel: {len(reachable)}")

    hoje = date.today()
    cache = le_cache_seguidores(hoje)
    leads, sem_resposta, do_cache = [], 0, 0
    for profile, address in reachable:
        followers = cache.get(profile.login.lower())
        if followers is None:
            followers = _seguidores(int(profile.id))
            time.sleep(HELIX_SLEEP_SECONDS)
            if followers is not None:
                anota_seguidores(profile.login.lower(), followers, hoje)
        else:
            do_cache += 1
        if followers is None:
            sem_resposta += 1
            continue
        if not publico.cabe(followers, profile.broadcaster_type):
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
                # Quem envia precisa saber o idioma: convite em portugues para
                # canal em ingles vira reclamacao de spam.
                "language": languages[profile.id].broadcaster_language,
            }
        )
    if do_cache:
        print(f"  {do_cache} contagens vieram do cache, nao gastaram chamada")
    if sem_resposta:
        # Sumir com lead em silencio e pior que perder: fica sem explicacao.
        print(f"  {sem_resposta} canais sem resposta da Twitch, ficaram de fora")
    return sorted(leads, key=lambda lead: int(lead["followers"]), reverse=True)


def split_ramp(
    leads: list[dict[str, str]], first_number: int, trilha: str = TARGET_LANGUAGE
) -> list[Path]:
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
        # Trilha no nome: `lote-11` e portugues (historico), `lote-en-1` e ingles.
        # O portao compara lote com lote da mesma trilha, porque publico novo tem
        # bounce e reclamacao desconhecidos e nao pode se esconder na media do
        # publico ja provado.
        posicao = first_number + offset
        sufixo = posicao if trilha == TARGET_LANGUAGE else f"{trilha}-{posicao}"
        path = CAMPAIGN_DIR / f"lote-{sufixo}.csv"
        if path.exists():
            raise FileExistsError(
                f"{path} ja existe; nao vou sobrescrever lote enviado"
            )
        write_rows(
            path,
            [
                {"email": lead["email"], "language": lead.get("language", trilha)}
                for lead in chunk
            ],
            ["email", "language"],
        )
        paths.append(path)
        start += size
    leftover = max(0, len(ordered) - start)
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
    "language",
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
    # Segunda leva de palavras. As primeiras 91 esgotaram: a colheita de
    # 2026-07-29 varreu ate a pagina 30 de cada uma e so 1 consulta em 364
    # trouxe algo, ou seja, o Google nao tem mais profundidade para elas. As
    # abaixo abrem fatias novas do indice. Os nomes de jogo nao sao chute:
    # saem do `sweep`, ordenados por quantos canais pt transmitiam cada um.
    "Grand Theft Auto V",
    "VALORANT",
    "Tibia",
    "League of Legends",
    "Counter-Strike",
    "Fortnite",
    "Dead by Daylight",
    "EA Sports FC 26",
    "Minecraft",
    "Palworld",
    "Call of Duty: Warzone",
    "PUBG: BATTLEGROUNDS",
    "Path of Exile",
    "ROBLOX",
    "Call of Duty",
    "Overwatch",
    "Marvel Rivals",
    "Red Dead Redemption II",
    "Arena Breakout: Infinite",
    "Dota 2",
    "Battlefield 6",
    "ARC Raiders",
    "eFootball",
    "Perfect World",
    "Rainbow Six Siege",
    "Rocket League",
    "World of Warcraft",
    "Apex Legends",
    "Albion Online",
    "Retro",
    "IRL",
    "MECCHA CHAMELEON",
    "Assassin's Creed Black Flag Resynced",
    "League of Legends: Wild Rift",
    "Virtual Casino",
    "Warframe",
    "DayZ",
    "Black Desert",
    "Project Zomboid",
    "Genshin Impact",
    "Hunt: Showdown 1896",
    "Rust",
    "Free Fire",
    "MU Online",
    "MARVEL TŌKON: Fighting Souls",
    "Art",
    "Resident Evil 4",
    "Co-working & Studying",
    "Deadlock",
    "Euro Truck Simulator 2",
    "Talk Shows & Podcasts",
    "ELDEN RING",
    "Shift at Midnight",
    "Teamfight Tactics",
    "Crypto",
    "F1 25",
    "Delta Force",
    "Forza Horizon 6",
    "Ragnarok Online",
    "Ragnarok Origin: Classic",
    "Music",
    "Zenless Zone Zero",
    "R.E.P.O.",
    "Escape from Tarkov",
    "Call of Duty: Modern Warfare III",
    "Cyberpunk 2077",
    "Mobile Legends: Bang Bang",
    "Honkai: Star Rail",
    "iRacing",
    "Diablo IV",
    "livepix",
    "streamlabs",
    "streamelements",
    "tipa.ai",
    "apoia.se",
    "picpay",
    "mercado pago",
    "catarse",
    "patreon",
    "nubank",
    "complexo rp",
    "rush rp",
    "cidade vida real",
    "gorila city",
    "alpha city",
    "nopixel br",
    "vida real rp",
    "bope rp",
    "tuga rp",
    "genesis rp",
    "midia kit",
    "media kit",
    "kit de midia",
    "patrocinio",
    "divulgacao",
    "colaboracoes",
    "contato empresarial",
    "para propostas",
    "negocios",
    "melhores momentos",
    "cortes do canal",
    "clipes",
    "react",
    "sorteio",
    "campeonato",
    "torneio",
    "ranked",
    "podcast",
    "canal secundario",
    # Terceira leva, e a primeira que nao tem chute nenhum: sao as frases
    # que aparecem na bio de quem PUBLICA email, comparadas com a bio de
    # quem nao publica (2.397 contra 8.970 bios reais da Helix). Ordenadas
    # pelo quanto a frase e mais comum no primeiro grupo. As duas levas
    # anteriores mostraram o caminho: nome de jogo traz canal de fora do
    # Brasil, frase de contato comercial traz quem tem email publico.
    "business",
    "inquiries",
    "business inquiries",
    "contact",
    "business contact",
    "comercial",
    "business email",
    "for business",
    "email para",
    "contacto",
    "for business inquiries",
    "mail para",
    "enquiries",
    "mail para contato",
    "inquires",
    "business inquires",
    "business enquiries",
    "contact pro",
    "mail pro",
    "contato contato",
    "contatos",
    "contact me",
    "com for",
    "business mail",
    "pra contato",
    "email de",
    "principalement",
    "email me",
    "email de contato",
    "email contato",
    "contato parcerias",
    "com for business",
    "com discord",
    "profissional contato",
    "partnerships",
    "partners",
    "games business",
    "for any",
    "everything",
    "enquires",
    "email pra contato",
    "email pra",
    "creator for",
    "comigo contato",
    "twitch partner",
    "inquiry",
    "inquiries please",
    "gamerbiz com",
    "gamerbiz",
    "content creator for",
    "contato profissional contato",
    "contact email",
    "business enquires",
    "any business",
    "well as",
    "we are",
    "stream business",
    "stopping by",
    "stopping",
    "please email",
    "partnership",
    "os dias contato",
    "mail de",
    "for business enquiries",
    "email for",
    "dias contato",
    "com https",
    "as well as",
    "with us",
    "veteran",
    "streamer business",
    "reach out",
    "my discord",
    "looking",
    "jogos contato",
    "inquiries email",
    "here business",
    "for any business",
    "correo",
    "canadian",
    "business inquiry",
    "business inquiries please",
    "bienvenue",
    "better",
    "aqui contato",
    "vindo contato",
    "variety gamer",
    "tous les",
    "to join the",
    "time business",
    "stream variety",
    "strategy",
    "spooky",
    "relax and",
    "profissional parcerias",
    "please contact",
    "player business",
    "parceria contato",
    "para contato profissional",
    "para contato contato",
    "member of",
    "member",
    "me playing",
    "mainly stream",
    "mail de contato",
    "love playing",
    "je joue",
    "fun business",
    "contato profissional parcerias",
    "contact me at",
    "community for",
    "com para",
    "business inquiries email",
    "buisness",
    "bem vindo contato",
    "00 contato",
    "vindos contato",
    "variety streamer who",
    "variety gaming",
    "to reach",
    "the internet",
    "the good",
    "streameuse",
    "stream todos los",
    "stream business email",
    "profissional parcerias propostas",
    "principalement sur",
    "parcerias propostas",
    "para contatos",
    "os dias email",
    "name's",
    "moi c'est",
    "mental health",
    "me and",
    "mail pra contato",
    "mail pra",
    "mail contato",
    "looking for",
    "like playing",
    "kr3w gg",
    "kontakt",
    "jugador",
    "je suis",
    "host of",
    "health",
    "gremlin",
    "games that",
    "games i'm",
    "gamer business",
    "gacha games",
    "from australia",
    "for stopping by",
    "for stopping",
    "focused on",
    "en live",
    "email me at",
    "el mundo",
    "driven",
    "dias email",
    "de contacto",
    "contato comercial contato",
    "comercial contato",
    "com instagram",
    "collabs",
    "chat contato",
    "certified",
    "casino",
    "canal mail",
    "called",
    "bem vindos contato",
    "any business inquiries",
    "anfragen",
    "ai contato",
    "ad contato",
    "your day",
    "women's",
    "with us business",
    "with love for",
    "with love",
    "vidéos",
    "vibes business",
    "variety streamer from",
    "us business",
    "twitch streamer",
    "too much",
    "together business",
    "time variety",
    "the stream business",
    "the good vibes",
    "the discord",
    "thanks for stopping",
    "swedish",
    "streameur",
    "streamer who plays",
    "streamer email",
    "streamer contact",
    "story driven",
    "spooky games",
    "space for",
    "sou parceira",
    "should",
    "scottish",
    "riot games",
    "relax and enjoy",
    "pronouns",
    "pro contact",
    "play fps",
    "people laugh",
    "partnered with",
    "partner and",
    "para contato parcerias",
    "panels",
    "outros jogos contato",
    "out for",
    "or you can",
    "or you",
    "on the internet",
    "on my stream",
    "my business email",
    "my business",
    "multigaming",
    "more business",
    "million",
    "me for",
    "making people",
    "mail profissional",
    "live contato",
    "les jours",
    "just gamer",
    "juntos contato",
    "join the discord",
    "join our",
    "join me on",
    "jeux vidéo",
    "inquiries please contact",
    "i'm the",
    "i'm also",
    "high energy",
    "hello everyone",
    "good at",
    "getting",
    "games contato",
    "gamer from",
    "galaxy",
    "french",
    "for partnerships",
    "for inquiries",
    "for contact",
    "for business inquires",
    "focusing on",
    "focusing",
    "enjoy the stream",
    "england",
    "engaging",
    "email profissional",
    "domingo das",
    "depuis",
    "de contenido",
    "dans la",
    "current",
    "creator for business",
    "contenu",
    "contact contact",
    "come for the",
    "come for",
    "com or",
    "collaborations",
    "catch me playing",
    "by and",
    "art and",
    "any pronouns",
    "any inquiries",
    "and you",
    "and try to",
    "and try",
    "and say",
    "and playing",
    "and join the",
    "and games",
    "and epic",
    "and enjoy the",
    "also like to",
    "agencia",
    "29 year old",
    "29 year",
    "para parcerias",
    "de contato",
    "contato para",
    "partner",
    "former",
    "time streamer",
    "he him",
    "full time streamer",
    "parcerias contato",
    "as well",
    "adventures",
    "there i'm",
    "socials",
    "everyone",
    "to get",
    "thursday",
    "parceiro da",
    "horror and",
    "everyday",
    "https me",
    "around",
    "she her",
    "todos los",
    "the time",
    "that loves",
    "streamer content creator",
    "streamer content",
    "powered",
    "pix para",
    "person",
    "on stream",
    "network",
    "check out",
    "all about",
    "you'll",
    "streamer and",
    "from the",
    "enjoy the",
    "with friends",
    "probably",
    "powered by",
    "out with",
    "join me",
    "hello there",
    "hello my name",
    "for all",
    "dreams",
    "australian",
    "aussie",
    "and stream",
    "and join",
    "all the",
    "variety streamer",
    "variety",
    "mainly",
    "todos los días",
    "los días",
    "australia",
    "and enjoy",
    "year old",
    "here to",
    "create",
    "contenido",
    "yapping",
    "who plays",
    "to stream",
    "to bring",
    "streamlabs com",
    "some variety",
    "scream",
    "playing games and",
    "play video",
    "occasional",
    "main game",
    "love for",
    "i'm just",
    "https streamlabs com",
    "https streamlabs",
    "here to have",
    "founder",
    "focused",
    "focus on",
    "enjoy your",
    "de jeux",
    "cs2 player",
    "check out my",
    "become",
    "and welcome",
    "and all",
    "affiliate",
    "content creator",
    "fun and",
    "full time",
    "who loves",
    "join the",
    "use código",
    "say hi",
    "hello i'm",
    "fps games",
    "playing games",
    "like to",
    "support",
    "streamer from",
    "having fun",
    "yourself",
    "your friendly",
    "you enjoy your",
    "worlds",
    "with my friends",
    "whether",
    "the vibes",
    "streamer here",
    "streamer de valorant",
    "stop by",
    "sou gabs",
    "schedule",
    "really",
    "played",
    "play video games",
    "play lot of",
    "play lot",
    "on all",
    "nuuvem",
    "nombre es",
    "my best",
    "moment",
    "mi nombre es",
    "mi nombre",
    "mas na",
    "links https",
    "in and",
    "hey there i'm",
    "here and",
    "hearts",
    "have you",
    "hang out with",
    "friend",
    "fridays",
    "for more",
    "follow to",
    "favourite",
    "enjoys",
    "emotes",
    "decisions",
    "das 16h",
    "cozy games and",
    "corner",
    "content creator streamer",
    "com ou",
    "chat and",
    "bringing",
    "aspiring",
    "artist and",
    "appreciate",
    "and variety",
    "and sometimes",
    "an artist",
    "ambassador",
    "addict",
    "content",
    "call me",
    "little",
    "creator",
    "streamer who",
    "lot of",
    "hey i'm",
    "friends",
    "variety of games",
    "juegos",
    "with the",
    "whatever",
    "paypal",
    "out my",
    "monday",
    "hey there",
    "bandai",
    "and my",
    "and more",
    "hi i'm",
    "playing",
    "laughs",
    "and love",
    "player for",
    "of games",
    "community",
    "hope you enjoy",
    "on twitch",
    "you're",
    "welcome in",
    "usually",
    "to play games",
    "stream todos",
    "some games",
    "safe space",
    "partnered",
    "occasionally",
    "my community",
    "me gusta",
    "laughs and",
    "i'm not",
    "horror games",
    "hello my",
    "have fun and",
    "games on",
    "at the",
    "also like",
    "all things",
    "welcome to the",
    "professional",
    "to have",
    "parceria",
    "making",
    "favorite",
    "enthusiast",
    "you will",
    "to have fun",
    "the community",
    "gameplay and",
    "name is",
    "my name is",
    "you can call",
    "games with",
    "can call me",
    "can call",
    "we play",
    "watch me",
    "vindo aproveite live",
    "the chaos",
    "my friends",
    "mi canal",
    "lover of",
    "i'm variety streamer",
    "i'm variety",
    "games but",
    "come chill",
    "and chat",
    "am variety",
    "feel free to",
    "feel free",
    "your favorite",
    "try to",
    "they them",
    "loves to",
    "gaming and",
    "games like",
    "and am",
    "my name",
    "with my",
    "on youtube",
    "love to",
    "i'm an",
    "catch me",
    "variety of",
    "hope you",
    "free to",
    "hi my name",
    "com live",
    "the world",
    "and have",
    "to make",
    "to join",
    "play variety of",
    "known as",
    "here for",
    "come hang",
    "you enjoy the",
    "valorant player",
    "to see",
    "to create",
    "the most",
    "thanks for",
    "streamer who loves",
    "streamer de fortnite",
    "quinta domingo",
    "my main",
    "juegos de",
    "hey guys",
    "for good",
    "creator streamer",
    "competitive player",
    "come to",
    "come say hi",
    "come say",
    "anos na",
    "games and",
    "on the",
    "cozy games",
    "to my channel",
    "thank you",
    "play variety",
    "my stream",
    "have fun",
    "to play",
    "com lives",
    "you for",
    "want to",
    "thank you for",
    "survival games",
    "stream for",
    "chaos and",
    "but you",
    "welcome to",
    "sou streamer de",
    "hang out",
    "with me",
    "my channel",
    "you enjoy",
    "and i'm",
    "hola soy",
    "anos sou streamer",
    "good vibes",
    "the game",
    "partir de",
    # Quarta leva, minerada de novo com a base ja crescida (5.324 bios com
    # email contra 2.397 da leva anterior). Portugues vem primeiro: medimos
    # que 90% do que a frase em ingles traz e canal de fora do Brasil, e nesta
    # leva so 15 das 328 frases tem marca de portugues.
    "contato comercia",
    "contatos parcerias",
    "jogos email",
    "19 00 contato",
    "ad contato profissional",
    "français",
    "para parceria",
    "por aqui contato",
    "todo el mundo",
    "twitch contato",
    "bienvenidos mi canal",
    "mi canal de",
    "canal de twitch",
    "todo el",
    "entrar em contato",
    "all business",
    "all business inquiries",
    "inquiries only",
    "streamer for",
    "to contact",
    "to contact me",
    "business inquiries only",
    "reach me",
    "for all business",
    "inquiries please email",
    "enquiries please",
    "ici on",
    "me business",
    "un peu",
    "business enquiries please",
    "correo de",
    "days week",
    "email is",
    "games business email",
    "bienvenue dans",
    "community business",
    "correo de contacto",
    "live tous",
    "live tous les",
    "out to",
    "streamer from the",
    "to reach out",
    "creator business",
    "games business inquiries",
    "inquires email",
    "installe",
    "installe toi",
    "partner business",
    "reach out to",
    "stay for the",
    "and say hi",
    "business inquires email",
    "d'autres",
    "email for business",
    "est business",
    "fueled",
    "hi business",
    "my email",
    "of games business",
    "parfois",
    "please email me",
    "say hi business",
    "sponsorships",
    "streamer play",
    "variety business",
    "and let's",
    "business anfragen",
    "collab",
    "content business",
    "cs2 player for",
    "email at",
    "here business email",
    "inquiries at",
    "inquiries email me",
    "need to",
    "passionné",
    "say hello",
    "sponsorship",
    "time business email",
    "welcome business",
    "any business enquiries",
    "around and",
    "business inquiries at",
    "enquiries please email",
    "for collabs",
    "games contact",
    "it business",
    "joue principalement",
    "les soirs",
    "live everyday",
    "me business email",
    "my names",
    "one of the",
    "please contact me",
    "professional cs2",
    "reach me at",
    "safe space for",
    "sponsor",
    "stay business",
    "streamer for business",
    "sur ma",
    "ubisoft partner",
    "business email is",
    "chat business",
    "content creator business",
    "dans le",
    "en live tous",
    "enquiries contact",
    "everyone business",
    "fueled by",
    "games for business",
    "is welcome",
    "mail de contacto",
    "of other games",
    "please send",
    "pm est",
    "presque",
    "professional cs2 player",
    "streams business",
    "time business inquiries",
    "tous les soirs",
    "vtuber from",
    "welcome my",
    "you business",
    "your stay business",
    "all socials",
    "am full",
    "am full time",
    "am here",
    "beyond",
    "bienvenue sur ma",
    "business enquiries contact",
    "business or",
    "bussiness",
    "but love",
    "chaos business",
    "come in",
    "contact info",
    "contacts",
    "discussions",
    "divers",
    "eldritch",
    "enjoy the vibes",
    "first playthroughs",
    "for business enquires",
    "for the good",
    "for work",
    "free to reach",
    "games business inquires",
    "get in",
    "good time business",
    "guy business",
    "happy to",
    "have any",
    "have fun business",
    "have laugh",
    "horror variety",
    "if you need",
    "inquires please",
    "m'appelle",
    "magical",
    "mais je",
    "mayhem",
    "me via",
    "message",
    "my chat",
    "my panels",
    "of variety",
    "on discord",
    "out business",
    "part time streamer",
    "principalement du",
    "purple",
    "semaine",
    "side of",
    "streaming variety",
    "streaming variety of",
    "sur le",
    "surtout",
    "talk to",
    "touche",
    "variety of other",
    "variety streamer business",
    "vtuber business",
    "what up",
    "youtube business",
    "an email",
    "and anime",
    "and artist",
    "and or",
    "anything else",
    "be sure",
    "be sure to",
    "behind",
    "business inquires please",
    "business inquiries reach",
    "business only",
    "business related",
    "business stuff",
    "can contact",
    "can contact me",
    "channel my",
    "chatting with",
    "choices",
    "collaboration",
    "commission",
    "contact pro contact",
    "currently playing",
    "dimanche",
    "du jeu",
    "email business",
    "emails",
    "father of",
    "for team",
    "from time",
    "from time to",
    "full time variety",
    "game for",
    "games email",
    "games while",
    "ghosts",
    "grandmaster",
    "happy to have",
    "her business",
    "here business inquiries",
    "hi you",
    "horreur",
    "in between",
    "in business",
    "in touch",
    "indigenous",
    "inquiries reach",
    "inquiries reach out",
    "inquiries to",
    "j'aime",
    "je joue principalement",
    "je m'appelle",
    "just like",
    "laugh business",
    "making people laugh",
    "monday friday",
    "more than",
    "nerd and",
    "of two",
    "play fps games",
    "pride guild",
    "professional inquiries",
    "professionnel",
    "retrouver",
    "saturdays",
    "serving",
    "she her business",
    "socials business",
    "stop by and",
    "streaming on",
    "teacher",
    "travel",
    "twitch pride",
    "variety streamer here",
    "variety streamer play",
    "vendredi",
    "welcome my name",
    "you can contact",
    "18 stream",
    "8pm est",
    "all inquiries",
    "all time",
    "am your",
    "an artist and",
    "and horror games",
    "and is",
    "and more business",
    "and proud",
    "at 9pm",
    "beautiful",
    "bon moment",
    "bringing the",
    "buisness email",
    "business inquiries to",
    "but most",
    "by and say",
    "channel my name",
    "chatting and",
    "check the",
    "chill et",
    "chinese",
    "come along",
    "come join me",
    "come vibe",
    "contact me on",
    "contact me via",
    "contactpro",
    "content business email",
    "cozy gamer",
    "create content",
    "dans mon",
    "de contact",
    "du lundi",
    "du lundi au",
    "enquiries please contact",
    "everyone is welcome",
    "for business email",
    "for collaborations",
    "fun business email",
    "fun business inquiries",
    "gambling",
    "game streamer",
    "gamer business email",
    "gamer girl",
    "games am",
    "gaming business",
    "get in touch",
    "going on",
    "hang out for",
    "health advocate",
    "hi business inquiries",
    "hi you can",
    "hiya i'm",
    "inquires please email",
    "it business inquiries",
    "jours partir",
    "jours partir de",
    "l'aventure",
    "les jours partir",
    "lundi au",
    "ma chaîne",
    "mail pro contact",
    "main game is",
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
    # Cada pagina tambem e cobrada: recomecar do zero paga de novo pelo que
    # a colheita anterior ja trouxe.
    serp.add_argument("--from-page", type=int, default=0)

    porlogin = sub.add_parser(
        "harvest-logins",
        help="pergunta ao Google o email de quem voce ja tem o login (pago)",
    )
    porlogin.add_argument(
        "--limite", type=int, default=200, help="quantos logins nesta rodada"
    )
    porlogin.add_argument(
        "--dominios", type=int, default=1, help="quantos dominios por login"
    )

    live = sub.add_parser("sweep", help="quem esta ao vivo agora")
    live.add_argument("--pages", type=int, default=120, help="teto por idioma")
    live.add_argument(
        "--idiomas",
        default=",".join(IDIOMAS_COLETA),
        help="idiomas a coletar, separados por virgula",
    )

    filtro = sub.add_parser("qualify", help="enriquece na Helix e filtra")
    padrao = Publico()
    filtro.add_argument("--min-seguidores", type=int, default=padrao.min_seguidores)
    filtro.add_argument("--max-seguidores", type=int, default=padrao.max_seguidores)
    # A coleta pega ingles tambem, mas so portugues entra na fila de envio por
    # padrao: o convite existe so em portugues.
    filtro.add_argument("--idiomas", default=TARGET_LANGUAGE)
    filtro.add_argument(
        "--sem-partner",
        action="store_true",
        help="descarta canal partner (a primeira leva usava isso)",
    )

    sub.add_parser("self-check", help="testa o extrator sem rede")

    split = sub.add_parser("batches", help="divide os leads nos lotes da rampa")
    split.add_argument("--start", type=int, default=6, help="numero do primeiro lote")
    split.add_argument(
        "--trilha", default=TARGET_LANGUAGE, help="idioma da trilha (pt ou en)"
    )

    args = parser.parse_args()
    if args.command == "self-check":
        _self_check()
        return

    if args.command == "batches":
        for path in split_ramp(read_rows(LEADS_PATH), args.start, args.trilha):
            print(f"{path}: {sum(1 for _ in path.open()) - 1} emails")
        return

    commands = {
        "harvest": lambda: harvest(
            KEYWORDS[args.skip : args.skip + args.keywords],
            DOMAINS[: args.domains],
            args.pages,
            args.from_page,
        ),
        "sweep": lambda: sweep(args.pages, tuple(args.idiomas.split(","))),
        "harvest-logins": lambda: harvest_logins(
            logins_sem_email(args.limite), DOMAINS[: args.dominios]
        ),
    }
    if args.command in commands:
        # A coleta demora minutos: so ler o arquivo depois dela evita apagar o
        # que outra coleta escreveu nesse meio tempo.
        collected = recolhe_diario() + commands[args.command]()
        existing = read_rows(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else []
        rows = merge_candidates(existing, collected)
        write_rows(CANDIDATES_PATH, rows, CANDIDATE_FIELDS)
        # Apagar so agora: o definitivo ja esta em disco, o diario cumpriu o papel.
        JOURNAL_PATH.unlink(missing_ok=True)
        print(
            f"{CANDIDATES_PATH}: {len(rows)} candidatos ({len(rows) - len(existing)} novos)"
        )
        return

    publico = Publico(
        min_seguidores=args.min_seguidores,
        max_seguidores=args.max_seguidores,
        inclui_partner=not args.sem_partner,
    )
    print(
        f"publico: {publico.min_seguidores} a {publico.max_seguidores} seguidores"
        f", partner {'incluido' if publico.inclui_partner else 'fora'}"
    )
    leads = qualify(
        read_rows(CANDIDATES_PATH), already_contacted(CAMPAIGN_DIR), publico
    )
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
