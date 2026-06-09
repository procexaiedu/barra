"""Regressão do arnês de geração (evals/sim/gerar_conversas._rodar).

Bug real achado no 1º baseline do flywheel: um cenário que QUEBRA dentro do grafo (ex.: a tool de
escrita estoura DENTRO do `conn.transaction()` que `_executar_idempotente` abre) deixa a conexão em
"transaction context"; o `conn.rollback()` seguinte então falha com `ProgrammingError` -- e, com
conexão COMPARTILHADA, essa 2ª exceção escapava do loop, DERRUBAVA o run inteiro e gravava o jsonl
VAZIO, perdendo os cenários bons já coletados. O fix: 1 conexão por cenário + rollback best-effort +
close sempre. Este teste crava que um cenário que quebra (e até um rollback que falha) NÃO mata o run
nem perde os parciais. PURO (mocka runner/jornada) -> roda em `make test`.
"""

import importlib
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

gc = importlib.import_module("evals.sim.gerar_conversas")
loop_mod = importlib.import_module("evals.sim.loop")


class _FakeCen:
    def __init__(self, nome, falha=False):
        self.nome = nome
        self.estado_inicial = {"atendimento_estado": "Triagem"}
        self.decidir_ato = None
        self.max_turnos = 4
        self.fechar_card = False
        self.falha = falha


class _FakeCliente:
    def __init__(self, falha):
        self.falha = falha


class _FakeConn:
    """Conn cujo rollback SEMPRE falha -- simula a conn em 'transaction context' após a tool estourar
    dentro do `_executar_idempotente`. O `close()` é o que de fato garante zero persistência."""

    def __init__(self):
        self.rolled = False
        self.closed = False

    async def rollback(self):
        self.rolled = True
        raise RuntimeError("Explicit rollback() forbidden within a Transaction context.")

    async def close(self):
        self.closed = True


def _passo_ok():
    return loop_mod.PassoJornada(
        indice=0,
        acao_mensagem="oi",
        acao_ato=None,
        bolha_ia="oi amor",
        estado_atendimento="Triagem",
        ia_pausada=False,
    )


async def test_rodar_isola_falha_preserva_parciais_e_sobrevive_rollback_quebrado(monkeypatch):
    conns: list[_FakeConn] = []

    class _FakeRunner:
        async def _conectar(self):
            c = _FakeConn()
            conns.append(c)
            return c

    monkeypatch.setattr(gc, "_carregar_runner", lambda: _FakeRunner())

    async def _fake_jornada(
        conn, seed, cliente, decidir_ato, *, max_turnos, apos_seed, fechar_card=False
    ):
        if (
            cliente.falha
        ):  # o cenário do meio quebra, como o externo_pix real (TypeError no bloqueio)
            raise TypeError("combine() argument 2 must be datetime.time, not None")
        return loop_mod.Trajetoria(passos=[_passo_ok()])

    monkeypatch.setattr(gc, "jornada", _fake_jornada)

    cens = [_FakeCen("a"), _FakeCen("b", falha=True), _FakeCen("c")]
    conversas = await gc._rodar(cens, lambda cen: _FakeCliente(cen.falha))

    # o cenário que quebrou (b) foi ISOLADO; os bons (a, c) sobreviveram e foram coletados
    assert [c["conversa_id"] for c in conversas] == ["a", "c"]
    # 1 conn POR cenário (isolamento); todas fechadas mesmo com rollback quebrado (zero persistência)
    assert len(conns) == 3
    assert all(c.closed for c in conns)
    assert all(c.rolled for c in conns)  # rollback best-effort foi TENTADO em cada uma
