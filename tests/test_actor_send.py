"""The Apify actor is the only thing that still sends the invite, and it calls the
repo's own functions without adapting them. So when one of those signatures moves,
nothing here fails until send time, on a batch the gate has already cleared. These
tests hold that seam: they build the real payload and read what would reach Resend.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "actor_main", ROOT / ".actor" / "main.py"
)
actor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(actor)


class FakeApify:
    """Only the two calls `enviar` makes on the key-value store."""

    def __init__(self, **records):
        self.records = records
        self.written = {}

    def le(self, store, key, default):
        return self.records.get(key, default)

    def grava(self, store, key, value):
        self.written[key] = value


@pytest.fixture
def sent_payloads(monkeypatch):
    """Whatever the actor would POST to Resend, without leaving the process."""
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json):
            posts.append(json)
            return FakeResponse()

    monkeypatch.setattr(actor.httpx, "Client", FakeClient)
    return posts


@pytest.fixture
def open_gate(monkeypatch):
    import campaign_stats

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(campaign_stats, "tally", lambda api_key, batches: {})
    monkeypatch.setattr(campaign_stats, "gate", lambda name, events, batches: 0)


def test_builds_one_payload_per_address_with_a_subject_and_a_body(
    open_gate, sent_payloads
):
    """The signature this depends on is `build_payloads(pairs, bodies_by_language)`.
    Passing bare addresses and a single body raises ValueError instead, which the
    actor would only discover with the batch already approved."""
    apify = FakeApify(
        fila=["a@exemplo.com", "b@exemplo.com"],
        contatados=[],
        historico=[],
    )

    assert actor.enviar(apify, "loja", {"minimo_por_dia": 1}) == 0

    payloads = sent_payloads[0]
    assert [p["to"] for p in payloads] == [["a@exemplo.com"], ["b@exemplo.com"]]
    assert all(p["subject"] and p["html"] for p in payloads)


def test_records_who_was_mailed_so_a_retry_never_writes_twice(open_gate, sent_payloads):
    apify = FakeApify(
        fila=["a@exemplo.com", "b@exemplo.com"],
        contatados=["ja@exemplo.com"],
        historico=[],
    )

    actor.enviar(apify, "loja", {"minimo_por_dia": 1})

    assert apify.written["contatados"] == [
        "a@exemplo.com",
        "b@exemplo.com",
        "ja@exemplo.com",
    ]
    assert apify.written["fila"] == []
    # O numero da trilha sai do historico, nao de um contador: a leva vira lote-1
    # e o proximo run le lote-1 para saber que o proximo e lote-2.
    assert apify.written["historico"] == [
        {"nome": "lote-1", "emails": ["a@exemplo.com", "b@exemplo.com"]}
    ]


def test_splits_a_mixed_queue_into_one_batch_per_language(open_gate, sent_payloads):
    """pt e en saem em levas separadas, cada uma com o nome da sua trilha, para o
    portao medir cada publico contra a sua propria reputacao."""
    apify = FakeApify(
        fila=[["br@exemplo.com", "pt"], ["us@exemplo.com", "en"]],
        contatados=[],
        historico=[{"nome": "lote-5", "emails": ["velho@exemplo.com"]}],
    )

    assert actor.enviar(apify, "loja", {"minimo_por_dia": 1}) == 0

    assert [r["nome"] for r in apify.written["historico"]] == [
        "lote-5",
        "lote-6",
        "lote-en-1",
    ]
    destinos = [p["to"][0] for chamada in sent_payloads for p in chamada]
    assert destinos == ["br@exemplo.com", "us@exemplo.com"]


def test_a_new_track_opens_with_at_most_fifty(open_gate, sent_payloads):
    """Trilha nova estreia com degrau de 50, nao com o teto: publico de bounce
    desconhecido nao leva um disparo grande de cara."""
    apify = FakeApify(
        fila=[[f"user{n}@exemplo.com", "en"] for n in range(80)],
        contatados=[],
        historico=[],
    )

    actor.enviar(apify, "loja", {"minimo_por_dia": 1, "maximo_por_dia": 150})

    enviados = [p["to"][0] for chamada in sent_payloads for p in chamada]
    assert len(enviados) == 50
    assert apify.written["historico"][0]["nome"] == "lote-en-1"


def test_one_track_blocked_does_not_stop_the_other(monkeypatch, sent_payloads):
    """Se o portao barra a trilha pt, a inglesa ainda sai. Uma trava numa trilha
    nao pode segurar a outra."""
    import campaign_stats

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(campaign_stats, "tally", lambda api_key, batches: {})
    monkeypatch.setattr(
        campaign_stats,
        "gate",
        lambda name, events, batches: 0 if name.startswith("lote-en-") else 1,
    )
    apify = FakeApify(
        fila=[["br@exemplo.com", "pt"], ["us@exemplo.com", "en"]],
        contatados=[],
        historico=[],
    )

    assert actor.enviar(apify, "loja", {"minimo_por_dia": 1}) == 0

    enviados = [p["to"][0] for chamada in sent_payloads for p in chamada]
    assert enviados == ["us@exemplo.com"]
    assert [r["nome"] for r in apify.written["historico"]] == ["lote-en-1"]


def test_skips_a_language_it_has_no_body_for(open_gate, sent_payloads):
    """Idioma sem corpo nao sai: mandar pt para quem le ingles volta como
    reclamacao de spam, nao como bounce. Seus leads ficam na fila e as outras
    trilhas seguem."""
    apify = FakeApify(
        fila=[["br@exemplo.com", "pt"], ["mistero@exemplo.com", "xx"]],
        contatados=[],
        historico=[],
    )

    actor.enviar(apify, "loja", {"minimo_por_dia": 1})

    enviados = [p["to"][0] for chamada in sent_payloads for p in chamada]
    assert enviados == ["br@exemplo.com"]
    assert apify.written["fila"] == [("mistero@exemplo.com", "xx")]
