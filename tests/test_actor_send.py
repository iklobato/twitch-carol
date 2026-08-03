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
        estado={"proximo_lote": 11},
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
        estado={"proximo_lote": 11},
        historico=[],
    )

    actor.enviar(apify, "loja", {"minimo_por_dia": 1})

    assert apify.written["contatados"] == [
        "a@exemplo.com",
        "b@exemplo.com",
        "ja@exemplo.com",
    ]
    assert apify.written["fila"] == []
    assert apify.written["estado"]["proximo_lote"] == 12


def test_refuses_a_language_it_has_no_body_for(sent_payloads):
    """The queue stores addresses only, and the image carries the Portuguese body
    alone. Turning English on without shipping the body would mail the Portuguese
    invite to people who cannot read it, and that comes back as a spam complaint,
    not as a bounce. `apify=None` proves it stops before touching any state."""
    assert actor.enviar(None, "loja", {"idiomas": "pt,en"}) == 1
    assert sent_payloads == []
