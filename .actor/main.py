"""Campanha do StreamIntel no Apify: colhe leads e envia o convite.

Roda o mesmo codigo do repo (`scripts/`) sem alterar nenhuma funcao dele. A
diferenca e de onde vem e para onde vai o estado: no notebook sao arquivos em
`data/campaign/`, aqui e um Key-Value Store, porque o container do Apify nasce e
morre sem disco. Como os caminhos do script sao relativos, basta descer o estado
para um diretorio temporario, entrar nele, e subir de volta no fim.

Dois modos, escolhidos pela entrada `acao`:

  colher  sweep na Twitch + busca no Google dentro do teto de gasto, qualifica na
          Helix e empilha os aprovados na fila.
  enviar  tira ate 150 da fila, passa pelo portao (bounce e spam do lote
          anterior, medidos na API do Resend) e manda pelo Resend.

Sem o SDK do Apify de proposito: ele arrasta o `crawlee`, que quebra com o
pydantic que o `core.config` usa. A API REST faz o mesmo com o httpx que ja esta
aqui, e o container fica menor.
"""

from __future__ import annotations

import calendar
import csv
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import httpx

API = "https://api.apify.com"
PRECO_POR_BUSCA_USD = 0.0025
CREDITO_MENSAL_USD = 29.0
LOJA = "streamintel-campanha"
CODIGO_DO_REPO = "/usr/src/app"
CORPO_HTML = "ai-generated-messages/broadcast-body.html"
POR_CHAMADA = 100
IDIOMA_PADRAO = "pt"


class Apify:
    """So o pedaco da API que a campanha usa."""

    def __init__(self, token: str) -> None:
        self._http = httpx.Client(params={"token": token}, timeout=120)

    def entrada(self) -> dict:
        loja = os.environ["APIFY_DEFAULT_KEY_VALUE_STORE_ID"]
        resposta = self._http.get(f"{API}/v2/key-value-stores/{loja}/records/INPUT")
        return resposta.json() if resposta.status_code == 200 else {}

    def loja_nomeada(self, nome: str) -> str:
        resposta = self._http.post(f"{API}/v2/key-value-stores", params={"name": nome})
        resposta.raise_for_status()
        return resposta.json()["data"]["id"]

    def le(self, loja: str, chave: str, padrao):
        resposta = self._http.get(f"{API}/v2/key-value-stores/{loja}/records/{chave}")
        return resposta.json() if resposta.status_code == 200 else padrao

    def grava(self, loja: str, chave: str, valor) -> None:
        resposta = self._http.put(
            f"{API}/v2/key-value-stores/{loja}/records/{chave}", json=valor
        )
        resposta.raise_for_status()

    def publica(self, itens: list[dict]) -> None:
        conjunto = os.environ["APIFY_DEFAULT_DATASET_ID"]
        resposta = self._http.post(f"{API}/v2/datasets/{conjunto}/items", json=itens)
        resposta.raise_for_status()

    def gasto_do_mes(self) -> float:
        resposta = self._http.get(f"{API}/v2/users/me/usage/monthly")
        resposta.raise_for_status()
        return resposta.json()["data"]["totalUsageCreditsUsdAfterVolumeDiscount"]


def buscas_permitidas(gasto: float, teto_usd: float, hoje: date) -> int:
    """Quanto da para gastar hoje sem estourar o mes. Divide o que sobra pelos
    dias que faltam no mes, e nao por semana: com a colheita rodando todo dia,
    dividir por semana faria a primeira rodada levar quase tudo."""
    sobra = min(teto_usd, CREDITO_MENSAL_USD) - gasto
    if sobra <= 0:
        return 0
    dias_restantes = calendar.monthrange(hoje.year, hoje.month)[1] - hoje.day + 1
    return int(sobra / dias_restantes / PRECO_POR_BUSCA_USD)


def escreve_csv(caminho: Path, linhas: list[dict], campos: list[str]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)


def prepara_pasta(apify: Apify, loja: str) -> Path:
    """Key-Value Store -> arquivos que o script do repo espera encontrar."""
    pasta = Path(tempfile.mkdtemp())
    escreve_csv(
        pasta / "data/campaign/candidates.csv",
        apify.le(loja, "candidatos", []),
        ["source", "login", "email", "hint"],
    )
    # Vira lote-0 porque `already_contacted` le todo `lote-*.csv`. Assim quem ja
    # recebeu fica de fora sem precisar tocar na funcao.
    escreve_csv(
        pasta / "data/campaign/lote-0.csv",
        [{"email": e} for e in apify.le(loja, "contatados", [])],
        ["email"],
    )
    # O cache de seguidores e o que faz a qualificacao diaria custar so os canais
    # novos, em vez de 6.000 chamadas na Helix todo dia.
    cache = apify.le(loja, "seguidores", [])
    if cache:
        escreve_csv(
            pasta / "data/campaign/seguidores.csv",
            cache,
            ["login", "followers", "data"],
        )
    # Sem este registro a colheita por login pagaria de novo, todo dia, por quem
    # nao tem email publico.
    tentados = apify.le(loja, "logins_tentados", [])
    if tentados:
        escreve_csv(
            pasta / "data/campaign/logins-tentados.csv", tentados, ["login", "data"]
        )
    origem = Path(CODIGO_DO_REPO) / CORPO_HTML
    if origem.exists():
        destino = pasta / CORPO_HTML
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(origem, destino)
    os.chdir(pasta)
    sys.path.insert(0, CODIGO_DO_REPO)
    sys.path.insert(0, f"{CODIGO_DO_REPO}/scripts")
    return pasta


def colher(apify: Apify, loja: str, entrada: dict) -> int:
    import prospect_leads as pl

    publico = pl.Publico(
        min_seguidores=int(entrada.get("min_seguidores", 500)),
        max_seguidores=int(entrada.get("max_seguidores", 100_000_000)),
        inclui_partner=bool(entrada.get("inclui_partner", True)),
    )
    paginas = int(entrada.get("paginas", 3))

    coleta = tuple(str(entrada.get("idiomas_coleta", "pt,en")).split(","))
    print(f"sweep: quem esta ao vivo agora em {'/'.join(coleta)}", flush=True)
    colhido = pl.sweep(int(entrada.get("paginas_sweep", 400)), coleta)

    estado = apify.le(loja, "estado", {})
    cursor = int(estado.get("cursor_palavras", 0))
    orcamento = buscas_permitidas(
        apify.gasto_do_mes(), float(entrada.get("teto_usd", 25)), date.today()
    )

    def checkpoint(rotulo: str) -> list[dict]:
        """Sobe candidatos + logins tentados para o KV. O dinheiro do Google so
        esta salvo depois disto: o run de 2026-08-28 travou no meio do harvest,
        morreu no timeout e perdeu tudo, porque so havia checkpoint no fim."""
        antigos = pl.read_rows(pl.CANDIDATES_PATH)
        candidatos = pl.merge_candidates(antigos, pl.recolhe_diario() + colhido)
        pl.write_rows(pl.CANDIDATES_PATH, candidatos, pl.CANDIDATE_FIELDS)
        apify.grava(loja, "candidatos", candidatos)
        if pl.LOGINS_TRIED_PATH.exists():
            apify.grava(loja, "logins_tentados", pl.read_rows(pl.LOGINS_TRIED_PATH))
        print(f"checkpoint ({rotulo}): {len(candidatos)} candidatos", flush=True)
        return candidatos

    total_inicial = len(pl.read_rows(pl.CANDIDATES_PATH))
    # O orcamento vai primeiro para a busca por login, que rende mais por dolar e
    # so traz brasileiro: sao 30 mil logins que o sweep ja achou sem email, 99%
    # deles canal em portugues. A busca por palavra fica de reserva para quando
    # esse bolso secar (dois meses, no ritmo atual).
    if orcamento:
        # Teto de 500 por run: o proxy SERP pendurou as conexoes perto do
        # request ~850 em DOIS runs seguidos de 2026-08-28 (o timeout do httpx
        # nao dispara), enquanto blocos de 500 fecharam limpos. O orcamento nao
        # gasto volta amanha, ja que buscas_permitidas divide pelo que resta do
        # mes.
        logins = pl.logins_sem_email(min(orcamento, 500))
        if logins:
            print(f"harvest por login: {len(logins)} logins", flush=True)
            colhido += pl.harvest_logins(logins, pl.DOMAINS[:1])
            candidatos = checkpoint("harvest salvo")
        else:
            cabem = orcamento // (paginas * len(pl.DOMAINS))
            fatia = (pl.KEYWORDS + pl.KEYWORDS)[cursor : cursor + cabem]
            print(f"sem login novo; harvest por palavra: {len(fatia)}", flush=True)
            colhido += pl.harvest(fatia, pl.DOMAINS, paginas)
            cursor = (cursor + cabem) % len(pl.KEYWORDS)
    else:
        print("sem orcamento para o harvest pago; so o sweep rodou", flush=True)

    candidatos = checkpoint("antes de qualificar")

    idiomas = tuple(str(entrada.get("idiomas", "pt")).split(","))
    leads = pl.qualify(
        candidatos, pl.already_contacted(pl.CAMPAIGN_DIR), publico, idiomas
    )

    fila = apify.le(loja, "fila", [])
    # Fila agora guarda (email, language) pares, não bare addresses.
    fila_emails = {
        item[0] if isinstance(item, (tuple, list)) else item for item in fila
    }
    novos = [
        (lead["email"].lower(), lead.get("language", "pt"))
        for lead in leads
        if lead["email"].lower() not in fila_emails
    ]
    print(
        f"{len(candidatos)} candidatos ({len(candidatos) - total_inicial} novos), "
        f"{len(leads)} qualificados, {len(novos)} entram na fila "
        f"(fila fica com {len(fila) + len(novos)})",
        flush=True,
    )

    if pl.FOLLOWERS_CACHE_PATH.exists():
        apify.grava(loja, "seguidores", pl.read_rows(pl.FOLLOWERS_CACHE_PATH))
    if pl.LOGINS_TRIED_PATH.exists():
        apify.grava(loja, "logins_tentados", pl.read_rows(pl.LOGINS_TRIED_PATH))
    apify.grava(loja, "fila", fila + novos)
    apify.grava(loja, "estado", {**estado, "cursor_palavras": cursor})
    if leads:
        apify.publica(leads)
    return 0


def _proximo_nome(nomes: list[str], idioma: str) -> tuple[str, int]:
    """Nome do proximo lote da trilha e quantos ela ja mandou. pt e `lote-N`, os
    outros `lote-<idioma>-N`, batendo com o que campaign_stats.trilha_e_numero le.
    Deriva o numero do historico em vez de um contador unico: com trilha por
    idioma, um contador so nao sabe de qual trilha e o proximo numero."""
    import campaign_stats as cs

    numeros = [
        cs.batch_number(nome) for nome in nomes if cs.trilha_e_numero(nome)[0] == idioma
    ]
    prefixo = "lote-" if idioma == IDIOMA_PADRAO else f"lote-{idioma}-"
    return f"{prefixo}{max(numeros, default=0) + 1}", len(numeros)


def _tamanho_do_lote(ja_enviados: int, maximo: int) -> int:
    """Trilha nova nunca foi testada: rampa a reputacao 50 -> 100 -> teto, em vez
    de estrear com um disparo grande para um publico de bounce desconhecido."""
    degraus = [50, 100]
    return degraus[ja_enviados] if ja_enviados < len(degraus) else maximo


def _carrega_corpos(envio) -> dict[str, str]:
    """broadcast-body.html e o idioma padrao; broadcast-body-<idioma>.html traz os
    outros. So o que tem corpo pode sair (idioma sem corpo fica na fila)."""
    corpos: dict[str, str] = {}
    for arquivo in sorted(Path(CORPO_HTML).parent.glob("broadcast-body*.html")):
        idioma = (
            envio.DEFAULT_LANGUAGE
            if arquivo.name == "broadcast-body.html"
            else arquivo.stem.split("-")[-1]
        )
        corpos[idioma] = envio.body_for_api(arquivo.read_text())
    return corpos


def _envia_lote(
    apify, loja, nome, escolhidos, corpos, envio, contatados, fila, historico
):
    """Manda um lote e grava o estado a cada bloco: container que morre no meio
    nao pode reenviar para quem ja recebeu quando o Apify tentar de novo. Muta
    `contatados`, `fila` e `historico`, que sao compartilhados entre as trilhas."""
    enviados: list[tuple[str, str]] = []
    with httpx.Client(
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"}, timeout=60
    ) as cliente:
        for inicio in range(0, len(escolhidos), POR_CHAMADA):
            bloco = escolhidos[inicio : inicio + POR_CHAMADA]
            resposta = cliente.post(
                envio.RESEND_BATCH_URL, json=envio.build_payloads(bloco, corpos)
            )
            resposta.raise_for_status()
            enviados += bloco
            enviados_emails = {e for e, _ in enviados}
            contatados |= enviados_emails
            apify.grava(loja, "contatados", sorted(contatados))
            fila[:] = [(e, lang) for e, lang in fila if e not in enviados_emails]
            apify.grava(loja, "fila", fila)
            print(f"  {nome}: enviados {len(enviados)}/{len(escolhidos)}", flush=True)
    historico.append({"nome": nome, "emails": [e for e, _ in enviados]})
    apify.grava(loja, "historico", list(historico))
    print(f"{nome}: {len(enviados)} enviados, fila fica com {len(fila)}")


def enviar(apify: Apify, loja: str, entrada: dict) -> int:
    comecar_em = entrada.get("comecar_em")
    if comecar_em and date.today().isoformat() < comecar_em:
        print(f"antes de {comecar_em}: a campanha do droplet ainda manda. Nao envio.")
        return 0

    import campaign_stats as cs
    import send_campaign_batch as envio

    maximo = int(entrada.get("maximo_por_dia", 150))
    minimo = int(entrada.get("minimo_por_dia", 30))
    # A fila guarda (email, idioma). Compatibilidade: string pura conta como pt.
    fila_raw = apify.le(loja, "fila", [])
    fila = [
        (
            (item[0].lower(), item[1])
            if isinstance(item, (tuple, list))
            else (item.lower(), IDIOMA_PADRAO)
        )
        for item in fila_raw
    ]
    contatados = set(apify.le(loja, "contatados", []))
    fila = [(e, lang) for e, lang in fila if e not in contatados]
    if len(fila) < minimo:
        print(f"fila com {len(fila)}, abaixo do minimo de {minimo}. Espero acumular.")
        return 0

    historico = apify.le(loja, "historico", [])
    nomes = [registro["nome"] for registro in historico]
    lotes = {
        registro["nome"]: {e.lower() for e in registro["emails"]}
        for registro in historico
    }
    corpos = _carrega_corpos(envio)

    # Uma leva por idioma, portugues primeiro. Trilha separada porque publico novo
    # tem bounce e reclamacao desconhecidos: junto no mesmo lote, o portao mede a
    # media e so descobre qual publico machucou o dominio depois de machucado.
    por_idioma: dict[str, list[tuple[str, str]]] = {}
    for e, lang in fila:
        por_idioma.setdefault(lang, []).append((e, lang))
    ordem = ([IDIOMA_PADRAO] if IDIOMA_PADRAO in por_idioma else []) + sorted(
        lang for lang in por_idioma if lang != IDIOMA_PADRAO
    )

    candidatos = []
    for lang in ordem:
        if lang not in corpos:
            print(
                f"sem corpo de email para '{lang}': {len(por_idioma[lang])} na fila "
                f"ficam para quando existir convite nesse idioma"
            )
            continue
        nome, ja = _proximo_nome(nomes, lang)
        escolhidos = por_idioma[lang][: _tamanho_do_lote(ja, maximo)]
        lotes[nome] = {e.lower() for e, _ in escolhidos}
        candidatos.append((nome, escolhidos))

    if not candidatos:
        print("nada com corpo para enviar")
        return 0

    # Uma leitura so do Resend serve para todos os portoes: o lote candidato ainda
    # nao tem evento, cada portao mede os anteriores da sua propria trilha.
    eventos = cs.tally(os.environ["RESEND_API_KEY"], lotes)

    algum = False
    for nome, escolhidos in candidatos:
        if cs.gate(nome, eventos, lotes):
            continue  # trilha barrada nao segura a outra
        _envia_lote(
            apify, loja, nome, escolhidos, corpos, envio, contatados, fila, historico
        )
        algum = True
    # Sem nenhum envio o run falha, para a trava aparecer em vez de sumir calada.
    return 0 if algum else 1


def main() -> int:
    # O `APIFY_TOKEN` que o container ganha vale so para o proprio run: nao cria
    # loja nomeada (que e onde mora o estado entre execucoes) nem le o consumo do
    # mes (que e o freio de gasto). Por isso o actor recebe um token de conta.
    token_conta = os.environ.get("APIFY_USER_TOKEN") or os.environ["APIFY_TOKEN"]
    # Sob LIMITED_PERMISSIONS o token do run nem /users/me consegue ler, e o
    # _serp_proxy_url do prospect_leads monta o proxy a partir dele. Os scripts
    # do repo leem APIFY_TOKEN do ambiente, entao o token de conta entra no
    # lugar antes de eles serem importados (quebrou a colheita em 2026-08-28).
    os.environ["APIFY_TOKEN"] = token_conta
    apify = Apify(token_conta)
    entrada = apify.entrada()
    loja = apify.loja_nomeada(LOJA)
    prepara_pasta(apify, loja)

    acoes = {"colher": colher, "enviar": enviar}
    acao = entrada.get("acao", "colher")
    if acao not in acoes:
        print(f"acao desconhecida: {acao}")
        return 1
    return acoes[acao](apify, loja, entrada)


if __name__ == "__main__":
    sys.exit(main())
