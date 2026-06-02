"""M3a: o contador `disclosure_tentativas` e idempotente cross-retry (mesmo turno_id conta 1x).

Sem DB: um `_StatefulConn` simula em memoria o `ON CONFLICT` de barravips.tool_calls e a coluna
`atendimentos.disclosure_tentativas`. A 1a invocacao "insere" a chave
(turno_id, _disclosure_incr, 0) e roda o UPDATE +1; o replay do MESMO turno_id bate no conflito e
devolve o `resultado` persistido SEM re-incrementar -- senao o contador subiria 2x e escalaria um
toque antes. Espelha o comportamento real de `_executar_idempotente` sem Postgres. A idempotencia
contra o banco real fica em tests/integracao/test_intercept_disclosure.py (needs_db).
"""

import importlib
import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.agente.contexto import ContextAgente

# nos/__init__ reexporta a funcao, sombreando o submodulo: importlib pega o modulo real.
mod = importlib.import_module("barra.agente.nos.intercept_disclosure")


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _StatefulConn:
    """tool_calls (ON CONFLICT) + atendimentos.disclosure_tentativas em memoria, compartilhados
    entre invocacoes -- o replay enxerga o estado deixado pela 1a passagem."""

    def __init__(self) -> None:
        self.tentativas = 0
        self._tool_calls: dict[tuple[Any, Any, Any], dict[str, Any] | None] = {}

    async def execute(self, query: str, params: Any = None) -> _Result:
        q = " ".join(query.split())
        if "INSERT INTO barravips.tool_calls" in q:
            chave = (params[0], params[1], params[2])  # turno_id, tool_name, call_idx
            if chave in self._tool_calls:
                return _Result(None)  # conflito -> ON CONFLICT DO NOTHING -> RETURNING vazio
            self._tool_calls[chave] = None
            return _Result({"turno_id": params[0]})
        if "SELECT resultado FROM barravips.tool_calls" in q:
            return _Result({"resultado": self._tool_calls[(params[0], params[1], params[2])]})
        if "UPDATE barravips.atendimentos" in q and "disclosure_tentativas + 1" in q:
            self.tentativas += 1
            return _Result({"disclosure_tentativas": self.tentativas})
        if "UPDATE barravips.tool_calls SET resultado" in q:
            # params = (resultado_json, turno_id, tool_name, call_idx)
            self._tool_calls[(params[1], params[2], params[3])] = json.loads(params[0])
            return _Result(None)
        return _Result(None)

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield self


class _Pool:
    def __init__(self, conn: _StatefulConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


async def _noop_reincidencia(_ctx: Any) -> None:
    """Isola o teste no contador de disclosure (a reincidencia por telefone tem teste proprio)."""
    return None


def _runtime(pool: _Pool, *, turno_id: str, cliente_id: str, atendimento_id: str) -> _Runtime:
    return _Runtime(
        ContextAgente(
            db_pool=pool,  # type: ignore[arg-type]
            redis=FakeRedis(),
            modelo_id=str(uuid4()),
            atendimento_id=atendimento_id,
            cliente_id=cliente_id,
            turno_id=turno_id,
        )
    )


_STATE = {"messages": [], "_categoria": "disclosure_attempt", "_confianca": "alta"}


async def test_contador_idempotente_no_replay_do_mesmo_turno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay do MESMO turno_id conta UMA vez e roteia igual (canned), nao 2x."""
    monkeypatch.setattr(mod, "_contabilizar_reincidencia", _noop_reincidencia)
    conn = _StatefulConn()
    pool = _Pool(conn)
    turno_id, cliente_id, atendimento_id = str(uuid4()), str(uuid4()), str(uuid4())
    rt = _runtime(pool, turno_id=turno_id, cliente_id=cliente_id, atendimento_id=atendimento_id)

    res1 = await mod.intercept_disclosure(dict(_STATE), rt)  # type: ignore[arg-type]
    res2 = await mod.intercept_disclosure(dict(_STATE), rt)  # replay: MESMO turno_id

    assert conn.tentativas == 1  # idempotente: NAO contou 2x
    assert res1.goto == "post_process"  # 1a: tentativas=1 (<3) -> negacao canned
    assert res2.goto == "post_process"  # replay: le tentativas=1 persistido, mesma rota


async def test_contador_soma_turnos_distintos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turnos DIFERENTES (mesma conversa) contam cada um -- o dedupe e por turno_id, nao global."""
    monkeypatch.setattr(mod, "_contabilizar_reincidencia", _noop_reincidencia)
    conn = _StatefulConn()
    pool = _Pool(conn)
    cliente_id, atendimento_id = str(uuid4()), str(uuid4())

    for _ in range(2):
        rt = _runtime(
            pool, turno_id=str(uuid4()), cliente_id=cliente_id, atendimento_id=atendimento_id
        )
        await mod.intercept_disclosure(dict(_STATE), rt)  # type: ignore[arg-type]

    assert conn.tentativas == 2  # cada turno conta uma vez
