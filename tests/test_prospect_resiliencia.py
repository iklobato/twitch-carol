"""A colheita nao pode morrer por causa de um canal.

Regressao de 2026-07-29: um `500` da Twitch no meio de 6.071 contagens de
seguidores derrubou a qualificacao inteira, jogando fora 15 minutos de chamadas
que ja tinham sido feitas. Aconteceu duas vezes no mesmo dia.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import prospect_leads as pl  # noqa: E402
from prospect_leads import _seguidores  # noqa: E402

from core.twitch import TwitchAuthError  # noqa: E402


def nao_espera(_segundos: float) -> None:
    """O backoff e real em producao; em teste seria so tempo perdido."""


class TwitchFalhando:
    """Falha as primeiras `vezes` chamadas e depois responde."""

    def __init__(self, vezes: int, resposta: int = 4_200) -> None:
        self.vezes = vezes
        self.resposta = resposta
        self.chamadas = 0

    def __call__(self, profile_id: int) -> int:
        self.chamadas += 1
        if self.chamadas <= self.vezes:
            raise TwitchAuthError("Twitch /channels/followers returned 500")
        return self.resposta


def test_devolve_a_contagem_quando_a_twitch_responde_de_primeira():
    twitch = TwitchFalhando(vezes=0)
    assert _seguidores(1, twitch, nao_espera) == 4_200
    assert twitch.chamadas == 1


def test_insiste_e_devolve_quando_a_falha_e_transitoria():
    twitch = TwitchFalhando(vezes=2)
    assert _seguidores(1, twitch, nao_espera) == 4_200
    assert twitch.chamadas == 3


def test_desiste_devolvendo_none_em_vez_de_derrubar_a_colheita():
    twitch = TwitchFalhando(vezes=99)
    assert _seguidores(1, twitch, nao_espera) is None
    assert twitch.chamadas == 3


def test_diario_guarda_a_coleta_conforme_ela_chega(tmp_path, monkeypatch):
    """Regressao: a coleta so gravava no fim, e cada consulta ao Google e paga.
    Um erro depois de 2.000 buscas jogava fora ~USD 5 de trabalho."""
    monkeypatch.chdir(tmp_path)
    pl.anota_no_diario([{"source": "serp", "login": "um", "email": "a@b.com", "hint": "x"}])
    pl.anota_no_diario([{"source": "serp", "login": "dois", "email": "c@d.com", "hint": "y"}])

    resgatado = pl.recolhe_diario()
    assert [linha["login"] for linha in resgatado] == ["um", "dois"]


def test_diario_vazio_quando_nao_houve_interrupcao(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert pl.recolhe_diario() == []


def test_cache_de_seguidores_ignora_contagem_velha(tmp_path, monkeypatch):
    """Canal cresce: contagem de semana passada nao pode decidir o filtro."""
    monkeypatch.chdir(tmp_path)
    hoje = date(2026, 8, 20)
    pl.anota_seguidores("recente", 4_000, hoje - timedelta(days=2))
    pl.anota_seguidores("velho", 9_000, hoje - timedelta(days=30))

    cache = pl.le_cache_seguidores(hoje)
    assert cache == {"recente": 4_000}


PAGINA = """
    <div>keilemeg fala com contato.keilemeg@gmail.com</div>
    <div>outro resultado qualquer: bruno.aku@gmail.com</div>
    <div>empresameikod@gmail.com do meikodrj</div>
"""


def test_aceita_email_que_carrega_o_login():
    assert pl.email_do_login("keilemeg", PAGINA) == ["contato.keilemeg@gmail.com"]


def test_aceita_quando_o_login_carrega_o_inicio_do_endereco():
    """meikodrj -> empresameikod@gmail.com: o pedaco 'meikod' aparece nos dois."""
    assert pl.email_do_login("meikodrj", PAGINA) == ["empresameikod@gmail.com"]


def test_recusa_email_de_outra_pessoa_na_mesma_pagina():
    """Regressao do teste pago de 2026-07-30: semelhanca aproximada aceitava
    'brino' -> 'bruno.aku@gmail.com'. Convite para a pessoa errada nao vira
    bounce, vira reclamacao de spam."""
    assert pl.email_do_login("brino", PAGINA) == []


def test_nao_repete_login_ja_perguntado(tmp_path, monkeypatch):
    """Cada consulta e paga: quem nao tem email publico nao pode ser perguntado
    de novo todo dia."""
    monkeypatch.chdir(tmp_path)
    assert pl.logins_ja_tentados() == set()
    pl.anota_login_tentado(["um", "dois"], date(2026, 8, 1))

    assert pl.logins_ja_tentados() == {"um", "dois"}
