"""OBS-07 — request-id propagado da API ate o worker nos logs JSON (OBS-03).

Cobre o fluxo ponta-a-ponta sem rede/DB/chave (gate `-m "not needs_key and not needs_db"`):
  (1) API: o middleware gera um request-id quando ausente e ecoa/preserva o X-Request-ID
      recebido (header da resposta);
  (2) enfileiramento: `enfileirar_turno` propaga o request_id no payload do job `processar_turno`;
  (3) worker: `processar_turno` binda request_id + turno_id como campos dos logs JSON estruturados.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
import structlog
from langchain_core.messages import AIMessage

from barra.core.logging import setup_logging
from barra.main import build_app
from barra.webhook.despacho import enfileirar_turno
from barra.workers.coordenador import processar_turno

_CONV_ID = "00000000-0000-0000-0000-0000000000c3"
_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# --- (1) API: middleware gera/captura o request-id -------------------------------------------


@pytest.mark.anyio
async def test_middleware_gera_request_id_quando_ausente() -> None:
    app = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")  # gerado quando o upstream nao manda


@pytest.mark.anyio
async def test_middleware_preserva_request_id_recebido() -> None:
    app = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health", headers={"X-Request-ID": "rid-upstream"})
    assert resp.headers["X-Request-ID"] == "rid-upstream"


# --- (2) enfileiramento: o request_id viaja no payload do job --------------------------------


@pytest.mark.anyio
async def test_enfileirar_turno_propaga_request_id() -> None:
    arq = MagicMock()
    arq.set = AsyncMock()
    arq.enqueue_job = AsyncMock()

    await enfileirar_turno(arq, UUID(_CONV_ID), "evo-1", request_id="rid-123")

    arq.enqueue_job.assert_awaited_once()
    chamada = arq.enqueue_job.await_args
    assert chamada.args[0] == "processar_turno"
    assert chamada.kwargs["request_id"] == "rid-123"


# --- (3) worker: request_id + turno_id viram campos do log JSON ------------------------------


class _FakeResult:
    async def fetchone(self) -> dict[str, Any]:
        return {
            "id": UUID("00000000-0000-0000-0000-0000000000bb"),
            "ia_pausada": True,  # gate -> log estruturado `turno_skipped`, sem invocar o grafo
            "estado": "Triagem",
            "modelo_id": UUID("00000000-0000-0000-0000-0000000000c1"),
            "cliente_id": UUID("00000000-0000-0000-0000-0000000000c2"),
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
    async def ainvoke(self, _entrada: Any, *, config: Any = None, context: Any = None) -> Any:
        return {"messages": [AIMessage(content="oi", usage_metadata=_USAGE)]}


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


@asynccontextmanager
async def _lock_ocupado(*_a: Any, **_k: Any) -> Any:
    from barra.core.redis import LockBusy

    raise LockBusy("lock:conv:test")
    yield None  # pragma: no cover — torna a funcao um asynccontextmanager valido


@pytest.fixture
def _logging_isolado() -> Iterator[None]:
    """Salva/restaura root logger e limpa contextvars (setup_logging + binds mutam global)."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        root.handlers, root.level = handlers, level
        structlog.contextvars.clear_contextvars()


@pytest.mark.anyio
async def test_worker_binda_request_id_e_turno_id_no_log_json(
    _logging_isolado: None, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakeredis.aioredis import FakeRedis

    import barra.workers.coordenador as coord

    monkeypatch.setattr(coord, "adquirir_lock", _lock_noop)

    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # type: ignore[attr-defined]
    ctx: dict[str, Any] = {
        "redis": redis,
        "db_pool": _FakePool(),
        "graph": _GrafoFake(),
        "settings": SimpleNamespace(deepseek_model_chat="deepseek-test"),
        "job_id": "job-obs07",
        "score": 1_700_000_000_000,
    }

    setup_logging(SimpleNamespace(log_level="INFO"))
    await redis.set(f"pending:conv:{_CONV_ID}", "1")  # gate de pendencia do coordenador
    await processar_turno(ctx, conversa_id=_CONV_ID, request_id="rid-e2e")

    linhas = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    registros = [json.loads(ln) for ln in linhas]
    skip = next(r for r in registros if r["event"].startswith("turno_skipped"))
    assert skip["request_id"] == "rid-e2e"
    assert skip["turno_id"]  # turno_id bindado como campo, junto do request_id


@pytest.mark.anyio
async def test_re_enqueue_em_lock_ocupado_preserva_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-defer por LockBusy mantem o request_id no turno recuperado (correlacao API->worker)."""
    from fakeredis.aioredis import FakeRedis

    import barra.workers.coordenador as coord

    monkeypatch.setattr(coord, "adquirir_lock", _lock_ocupado)

    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # type: ignore[attr-defined]
    ctx: dict[str, Any] = {
        "redis": redis,
        "db_pool": _FakePool(),
        "graph": _GrafoFake(),
        "settings": SimpleNamespace(deepseek_model_chat="deepseek-test"),
        "job_id": "job-obs07",
        "score": 1_700_000_000_000,
    }

    await processar_turno(ctx, conversa_id=_CONV_ID, request_id="rid-redefer")

    redis.enqueue_job.assert_awaited_once()
    chamada = redis.enqueue_job.await_args
    assert chamada.args[0] == "processar_turno"
    assert chamada.kwargs["request_id"] == "rid-redefer"
