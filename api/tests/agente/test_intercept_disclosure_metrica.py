"""Metrica AGENTE_ESCALADA no intercept_disclosure: jailbreak e disclosure caem em bucket=defesa.

Unit test sem DB: `abrir_handoff` (collaborator que exige Postgres) e trocado por um no-op via
monkeypatch e o pool/conn sao fakes — o que esta sob teste e o incremento do counter feito pelo
proprio `intercept_disclosure` APOS cada `abrir_handoff`. O registry do prometheus_client e
global, entao medimos o delta (antes/depois) por (bucket, motivo) p/ nao colidir com outros testes.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fakeredis.aioredis import FakeRedis
from langgraph.graph import END
from langgraph.types import Command
from prometheus_client import REGISTRY

from barra.agente.contexto import ContextAgente

# `nos/__init__.py` reexporta a funcao `intercept_disclosure`, sombreando o atributo de submodulo
# de mesmo nome; importlib pega o modulo real (de sys.modules) p/ o monkeypatch de `abrir_handoff`.
mod = importlib.import_module("barra.agente.nos.intercept_disclosure")


async def _abrir_handoff_noop(conn: Any, **kwargs: Any) -> None:
    return None


class _FakeResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any]:
        return self._row


class _FakeConn:
    """Conn fake: o UPDATE de disclosure_tentativas devolve `tentativas` (>=3 -> escala)."""

    def __init__(self, tentativas: int) -> None:
        self._tentativas = tentativas

    async def execute(self, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult({"disclosure_tentativas": self._tentativas})


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(pool: _FakePool) -> _Runtime:
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=FakeRedis(),  # contador de reincidência (SEC-JB-02): n=1, não escala nem soma métrica
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _valor_defesa(motivo: str) -> float:
    valor = REGISTRY.get_sample_value(
        "agente_escalada_total", {"bucket": "defesa", "motivo": motivo}
    )
    return valor or 0.0


async def test_jailbreak_incrementa_escalada_bucket_defesa(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "abrir_handoff", _abrir_handoff_noop)
    runtime = _runtime(_FakePool(_FakeConn(0)))
    antes = _valor_defesa("jailbreak_attempt")
    state = {"messages": [], "_categoria": "jailbreak_attempt", "_confianca": "alta"}

    res = await mod.intercept_disclosure(state, runtime)  # type: ignore[arg-type]

    assert isinstance(res, Command)
    assert res.goto == END
    assert _valor_defesa("jailbreak_attempt") == antes + 1


async def test_disclosure_insistente_incrementa_escalada_bucket_defesa(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "abrir_handoff", _abrir_handoff_noop)
    # tentativas=3 (>=3) -> caminho de escala (handoff + END).
    runtime = _runtime(_FakePool(_FakeConn(3)))
    antes = _valor_defesa("disclosure_insistente")
    state = {"messages": [], "_categoria": "disclosure_attempt", "_confianca": "alta"}

    res = await mod.intercept_disclosure(state, runtime)  # type: ignore[arg-type]

    assert isinstance(res, Command)
    assert res.goto == END
    assert _valor_defesa("disclosure_insistente") == antes + 1
