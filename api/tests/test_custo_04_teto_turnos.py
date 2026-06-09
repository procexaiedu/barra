"""CUSTO-04: teto de turnos por conversa/dia escala em vez de queimar orcamento ate as 24h.

Cobre o DoD sem tocar a API real (grafo FAKE) nem o banco (pool/conn mockados), entao roda no
gate `-m "not needs_key and not needs_db"`. O Redis e o `fakeredis` efemero (semantica real de
`get`/`set`), com `enqueue_job` trocado por AsyncMock (que o FakeRedis nao tem).

(a) N turnos ate o teto processam normal (grafo invocado, `enviar_turno` despachado); o turno
    N+1 dispara `escalar_por_exaustao(motivo="teto_turnos")` e NAO processa (sem grafo, sem
    bolha ao cliente).
(b) o motivo `teto_turnos` mapeia no bucket `capacidade` (default, igual a exaustao_iteracoes)
    + handoff para Fernando (tipo=outro) — sem precisar de entrada nova em service.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fakeredis.aioredis import FakeRedis
from langchain_core.messages import AIMessage

from barra.dominio.escaladas.modelos import TipoEscalada
from barra.workers.coordenador import escalar_por_exaustao, processar_turno

_ATEND_ID = UUID("00000000-0000-0000-0000-0000000000bb")
_MODELO_ID = UUID("00000000-0000-0000-0000-0000000000c1")
_CLIENTE_ID = UUID("00000000-0000-0000-0000-0000000000c2")
_CONV_ID = "00000000-0000-0000-0000-0000000000c3"

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- fakes de DB (sem Postgres) --------------------------------------------------------------


class _FakeResult:
    async def fetchone(self) -> dict[str, Any]:
        return {
            "id": _ATEND_ID,
            "ia_pausada": False,
            "estado": "Triagem",
            "modelo_id": _MODELO_ID,
            "cliente_id": _CLIENTE_ID,
            "conversa_id": UUID(_CONV_ID),
        }

    async def fetchall(self) -> list[dict[str, Any]]:
        return []


class _FakeConn:
    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult()

    def transaction(self) -> _FakeConn:
        return self

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConn()


class _GrafoFake:
    """ainvoke devolve uma AIMessage fixa (texto + usage) e conta as invocacoes."""

    def __init__(self) -> None:
        self.chamadas = 0

    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        self.chamadas += 1
        return {"messages": [AIMessage(content="oi amor", usage_metadata=_USAGE)]}


class _GrafoQueFalha:
    """ainvoke levanta — simula um turno que cai no `except Exception` e e retentado pelo ARQ."""

    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        raise RuntimeError("boom")


class _FakeSettings:
    anthropic_modelo_principal = "claude-test"


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _ctx(redis: FakeRedis, graph: _GrafoFake) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": _FakePool(),
        "graph": graph,
        "settings": _FakeSettings(),
        "job_id": "job-custo04",
        "score": 1_700_000_000_000,
    }


# --- (a) teto estoura -> escala e nao processa ------------------------------------------------


async def test_teto_turnos_escala_no_excedente_e_nao_processa() -> None:
    redis = _redis_fake()
    graph = _GrafoFake()

    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.TETO_TURNOS_DIA", 2),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()) as mock_escalar,
    ):
        # turnos 1 e 2 (<= teto) processam normal; cada chamada e um turno (o gate de
        # pendencia exige pending:conv setado; o drain o consome -> 1 iter por chamada).
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        await processar_turno(_ctx(redis, graph), conversa_id=_CONV_ID)
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        await processar_turno(_ctx(redis, graph), conversa_id=_CONV_ID)
        assert graph.chamadas == 2
        mock_escalar.assert_not_awaited()

        # turno 3 (N+1) estoura o teto: escala teto_turnos e NAO invoca o grafo.
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        await processar_turno(_ctx(redis, graph), conversa_id=_CONV_ID)

    assert graph.chamadas == 2  # o grafo NAO rodou no turno excedente
    mock_escalar.assert_awaited_once()
    assert mock_escalar.await_args.kwargs["motivo"] == "teto_turnos"

    # os 2 turnos validos despacharam enviar_turno; o excedente nao mandou bolha ao cliente.
    enviados = [
        c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"
    ]
    assert len(enviados) == 2


# --- (b) mapping do motivo novo (sem tocar service.py) ----------------------------------------


async def test_motivo_teto_turnos_mapeia_bucket_capacidade() -> None:
    """teto_turnos -> handoff Fernando (tipo=outro) + metrica bucket=capacidade (mapping real)."""
    with (
        patch("barra.dominio.escaladas.service.abrir_handoff", new=AsyncMock()) as mock_handoff,
        patch("barra.workers.coordenador.AGENTE_ESCALADA") as mock_metric,
    ):
        await escalar_por_exaustao(_FakePool(), _ATEND_ID, "turno-custo04", motivo="teto_turnos")

    mock_handoff.assert_awaited_once()
    kwargs = mock_handoff.await_args.kwargs
    assert kwargs["tipo"] == TipoEscalada.outro
    assert kwargs["responsavel"] == "Fernando"
    assert kwargs["observacao"] == "teto_turnos"
    mock_metric.labels.assert_called_once_with("capacidade", "teto_turnos")


# --- (c) retry-safety: turno que falha nao conta para o teto ----------------------------------


async def test_turno_que_falha_nao_conta_para_o_teto() -> None:
    """O incremento e pos-sucesso: um turno cujo grafo levanta (e seria retentado pelo ARQ) NAO
    infla o contador, entao o retry nao escala teto_turnos falso por flakiness de infra."""
    redis = _redis_fake()
    chave = f"turnos:conv:{_CONV_ID}:{datetime.now(UTC):%Y-%m-%d}"

    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await redis.set(f"pending:conv:{_CONV_ID}", "1")
        with pytest.raises(RuntimeError):
            await processar_turno(_ctx(redis, _GrafoQueFalha()), conversa_id=_CONV_ID)

    # o grafo falhou DEPOIS da checagem read-only -> o contador nunca foi escrito.
    assert await redis.get(chave) is None
