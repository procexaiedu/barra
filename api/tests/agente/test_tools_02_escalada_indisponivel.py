"""TOOLS-02: 5xx/timeout persistente da API do LLM (Anthropic) vira escalada propria.

Cobre o DoD: um erro persistente da API do LLM durante `graph.ainvoke` no `processar_turno`
escala como `motivo="modelo_indisponivel"` (em vez de cair no `except Exception` generico que
joga para o retry do ARQ) e esse motivo mapeia para o `bucket="infra"` via o caminho real
`mapear_motivo`/`mapear_bucket` -> `abrir_handoff` (Fernando, `tipo=outro`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import pytest
from anthropic import APIStatusError, APITimeoutError, RateLimitError

from barra.dominio.escaladas.modelos import TipoEscalada
from barra.workers.coordenador import escalar_por_exaustao, processar_turno

_ATEND_ID = UUID("00000000-0000-0000-0000-0000000000bb")
_MODELO_ID = UUID("00000000-0000-0000-0000-0000000000c1")
_CLIENTE_ID = UUID("00000000-0000-0000-0000-0000000000c2")
_CONV_ID = "00000000-0000-0000-0000-0000000000c3"


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
    def connection(self) -> _FakeConn:
        return _FakeConn()


class _FakeRedis:
    def __init__(self) -> None:
        # pending pre-semeado: o gate de pendencia do coordenador exige mensagem nova
        self._dados: dict[str, Any] = {f"pending:conv:{_CONV_ID}": "1"}

    async def set(self, chave: str, valor: Any = "1", **_k: Any) -> bool:
        self._dados[chave] = valor
        return True

    async def delete(self, chave: str, *_a: Any, **_k: Any) -> None:
        self._dados.pop(chave, None)

    async def get(self, chave: str, *_a: Any, **_k: Any) -> Any:
        return self._dados.get(chave)


class _FakeGraph:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
        # erro persistente da API do LLM (Anthropic) — o no llm ja re-levanta esses erros.
        raise self._exc


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _erros_persistentes() -> list[BaseException]:
    resp = httpx.Response(500, request=_req())
    return [
        APIStatusError("server error", response=resp, body=None),
        RateLimitError("rate limited", response=httpx.Response(429, request=_req()), body=None),
        APITimeoutError(request=_req()),
    ]


class _FakeSettings:
    deepseek_model_chat = "deepseek-test"


def _ctx(exc: BaseException) -> dict[str, Any]:
    return {
        "redis": _FakeRedis(),
        "db_pool": _FakePool(),
        "graph": _FakeGraph(exc),
        "settings": _FakeSettings(),
        "job_id": "job-tools02",
        "score": 1000,
    }


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


@pytest.mark.parametrize("exc", _erros_persistentes(), ids=lambda e: type(e).__name__)
async def test_erro_persistente_api_aciona_escalada_modelo_indisponivel(exc: BaseException) -> None:
    """graph.ainvoke -> erro persistente da API -> escalar_por_exaustao(motivo=modelo_indisponivel).

    Cobre os 3 erros desviados (RateLimitError, APITimeoutError, APIStatusError): se alguem
    remover/reordenar um membro da tupla do except, o caso correspondente falha.
    """
    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()) as mock_escalar,
    ):
        await processar_turno(_ctx(exc), conversa_id=_CONV_ID)

    mock_escalar.assert_awaited_once()
    assert mock_escalar.await_args.kwargs["motivo"] == "modelo_indisponivel"


async def test_motivo_modelo_indisponivel_mapeia_bucket_infra() -> None:
    """modelo_indisponivel -> handoff Fernando (tipo=outro) + metrica bucket=infra (mapping real)."""
    with (
        patch("barra.dominio.escaladas.service.abrir_handoff", new=AsyncMock()) as mock_handoff,
        patch("barra.workers.coordenador.AGENTE_ESCALADA") as mock_metric,
    ):
        await escalar_por_exaustao(
            _FakePool(), _ATEND_ID, "turno-tools02", motivo="modelo_indisponivel"
        )

    mock_handoff.assert_awaited_once()
    kwargs = mock_handoff.await_args.kwargs
    assert kwargs["tipo"] == TipoEscalada.outro
    assert kwargs["responsavel"] == "Fernando"
    assert kwargs["observacao"] == "modelo_indisponivel"
    mock_metric.labels.assert_called_once_with("infra", "modelo_indisponivel")
