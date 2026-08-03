"""Portao que libera (ou barra) cada lote agendado da campanha no droplet.

Barrar errado custa um dia de atraso. Liberar errado manda email de verdade para
centenas de pessoas, ou manda duas vezes para as mesmas. Todo caso duvidoso barra.
"""

import collections
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from campaign_stats import gate, load_batches  # noqa: E402

BATCHES = {f"lote-{n}": {f"pessoa{n}@exemplo.com"} for n in range(6, 11)}


def events(**por_lote: dict[str, int]) -> dict[str, collections.Counter]:
    todos = collections.defaultdict(collections.Counter)
    todos.update(
        {name: collections.Counter(counts) for name, counts in por_lote.items()}
    )
    return todos


def test_libera_quando_o_anterior_entregou_limpo():
    assert gate("lote-8", events(**{"lote-7": {"delivered": 80}}), BATCHES) == 0


def test_barra_lote_ja_enviado():
    """Timer que dispara duas vezes nao pode mandar o mesmo email de novo."""
    assert (
        gate(
            "lote-8",
            events(**{"lote-7": {"delivered": 80}, "lote-8": {"delivered": 120}}),
            BATCHES,
        )
        == 1
    )


def test_barra_quando_o_anterior_passou_do_limite_de_bounce():
    ruim = {"delivered": 76, "bounced": 4}  # 5%, acima dos 3%
    assert gate("lote-8", events(**{"lote-7": ruim}), BATCHES) == 1


def test_barra_com_qualquer_reclamacao_de_spam():
    assert (
        gate(
            "lote-8", events(**{"lote-7": {"delivered": 79, "complained": 1}}), BATCHES
        )
        == 1
    )


def test_barra_quando_o_lote_anterior_nao_saiu():
    """Regressao: o portao olhava o ultimo lote enviado, entao o lote-10 saia na
    quinta conferindo o lote-7, mesmo com o lote-9 falhando na quarta."""
    assert gate("lote-10", events(**{"lote-7": {"delivered": 80}}), BATCHES) == 1


def test_barra_lote_que_nao_existe():
    assert gate("lote-99", events(**{"lote-7": {"delivered": 80}}), BATCHES) == 1


@pytest.mark.parametrize("bounces,esperado", [(2, 0), (3, 1)])
def test_limite_de_bounce_e_3_porcento(bounces, esperado):
    counts = {"delivered": 100 - bounces, "bounced": bounces}
    assert gate("lote-8", events(**{"lote-7": counts}), BATCHES) == esperado


TRILHAS = {
    "lote-10": {"br@exemplo.com"},
    "lote-11": {"br2@exemplo.com"},
    "lote-en-1": {"us@exemplo.com"},
    "lote-en-2": {"us2@exemplo.com"},
}


def test_trilha_nova_pode_abrir_sem_lote_anterior():
    """O primeiro lote em ingles nao tem o que medir; quem segura o risco e o
    tamanho do degrau (50), nao o portao."""
    assert gate("lote-en-1", events(), TRILHAS) == 0


def test_lote_em_ingles_mede_contra_ingles_e_nao_contra_o_portugues():
    """Publico novo nao herda a reputacao construida com brasileiros: se o
    primeiro lote em ingles nao saiu, o segundo nao sai."""
    enviados = events(**{"lote-10": {"delivered": 121}, "lote-11": {"delivered": 200}})

    assert gate("lote-en-2", enviados, TRILHAS) == 1


def test_bounce_do_ingles_nao_trava_a_trilha_portuguesa():
    ruim = {"delivered": 45, "bounced": 5}  # 10% na trilha inglesa
    enviados = events(**{"lote-10": {"delivered": 121}, "lote-en-1": ruim})

    assert gate("lote-11", enviados, TRILHAS) == 0


def test_load_batches_unpacks_the_language_column(tmp_path, monkeypatch):
    """`read_batch` returns (address, language) pairs since the English track
    landed. Keeping the raw tuples makes every batch lookup miss, so the gate
    stops telling a batch that went out from one that never did, and it reads
    every batch as unsent.
    """
    (tmp_path / "lote-1.csv").write_text("email,language\nAlice@Exemplo.com,pt\n")
    (tmp_path / "lote-2.csv").write_text("email\nbob@exemplo.com\n")  # pre-language
    monkeypatch.setattr("campaign_stats.BATCH_DIR", tmp_path)
    monkeypatch.setattr("send_campaign_batch.BATCH_DIR", tmp_path)

    assert load_batches() == {
        "lote-1": {"alice@exemplo.com"},
        "lote-2": {"bob@exemplo.com"},
    }
