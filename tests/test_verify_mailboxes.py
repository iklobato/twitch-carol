"""Sondagem SMTP que tira caixas mortas da fila. Dropar um lead vivo custa
dinheiro; por isso so 'morta' com um nao-existe explicito do servidor, e um
dominio inteiro 'morto' e tratado como bloqueio do nosso IP, nao lista morta."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "verify_mailboxes", ROOT / "scripts" / "verify_mailboxes.py"
)
vm = importlib.util.module_from_spec(_spec)
sys.modules["verify_mailboxes"] = vm
_spec.loader.exec_module(vm)


class FakeSMTP:
    def __init__(self, respostas):
        self.respostas = respostas

    def ehlo(self, host):
        return (250, b"ok")

    def mail(self, remetente):
        return (250, b"ok")

    def rcpt(self, endereco):
        return self.respostas.get(endereco, (250, b"2.1.5 ok"))

    def quit(self):
        return None


def conecta_com(respostas):
    return lambda mx, porta, timeout: FakeSMTP(respostas)


def test_classifica_so_dropa_nao_existe_explicito():
    assert vm.classifica(250, "2.1.5 ok") == "viva"
    assert vm.classifica(550, "5.1.1 the account does not exist") == "morta"
    assert vm.classifica(550, "5.1.1 user unknown") == "morta"
    # 550 generico (bloqueio/politica) NAO e morte: mantem
    assert vm.classifica(550, "5.7.1 blocked by policy") == "incerta"
    assert vm.classifica(451, "greylisted, try later") == "incerta"
    assert vm.classifica(421, "too many connections") == "incerta"


def test_sonda_dominio_separa_viva_morta_e_incerta():
    respostas = {
        "viva@gmail.com": (250, b"2.1.5 ok"),
        "morta@gmail.com": (550, b"5.1.1 does not exist"),
        "cinza@gmail.com": (451, b"greylisted"),
    }
    enderecos = list(respostas)
    out = vm.sonda_dominio("mx", enderecos, conectar=conecta_com(respostas), pausa=0)
    assert out == {
        "viva@gmail.com": "viva",
        "morta@gmail.com": "morta",
        "cinza@gmail.com": "incerta",
    }


def test_dominio_inteiro_morto_e_tratado_como_bloqueio_e_mantido():
    """Se TODO endereco (>=5) volta morto, cheira a bloqueio do nosso IP, nao a
    lista morta: mantem todos em vez de dropar uma lista boa inteira."""
    respostas = {f"u{n}@dominio.com": (550, b"5.1.1 does not exist") for n in range(6)}
    out = vm.sonda_dominio(
        "mx", list(respostas), conectar=conecta_com(respostas), pausa=0
    )
    assert set(out.values()) == {"incerta"}


def test_erro_de_conexao_mantem_todos():
    def explode(mx, porta, timeout):
        raise OSError("connection refused")

    out = vm.sonda_dominio("mx", ["a@x.com", "b@x.com"], conectar=explode, pausa=0)
    assert out == {"a@x.com": "incerta", "b@x.com": "incerta"}
