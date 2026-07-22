"""registrar_extracao: NAO enfileira o card loc_pin enquanto `_card_loc_pin` e NotImplemented.

Sem DB nem LLM: `_executar_idempotente` (o efeito de dominio) e mockado para devolver
`enviar_pin=True` (o caminho do atendimento interno qualificado), provando que mesmo com o
sinal ligado a tool nao enfileira `card:loc_pin` — o renderer em workers/envio.py ainda
levanta NotImplementedError e o job so falharia 5x. O `.coroutine` e a corrotina crua do @tool
(injeta o runtime fora do schema do LLM), espelhando test_consultar_agenda.py.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import ToolException

import barra.agente.ferramentas.extracao as extracao
from barra.agente.ferramentas.extracao import registrar_extracao
from barra.dominio.agenda.service import AntecedenciaInsuficiente
from barra.dominio.atendimentos.service import ParPrecoDuracaoInvalido

# .coroutine e a corrotina crua do @tool; .ainvoke({...}) NAO injeta runtime, .coroutine sim.
_chamar = registrar_extracao.coroutine  # type: ignore[attr-defined]


class _PoolNoOp:
    """Pool fake: `_executar_idempotente` esta mockado, entao a conexao nao e usada de fato."""

    @asynccontextmanager
    async def connection(self) -> Any:
        yield object()


class _Ctx:
    def __init__(self, redis: Any) -> None:
        self.db_pool = _PoolNoOp()
        self.redis = redis
        self.atendimento_id = "00000000-0000-0000-0000-000000000001"
        self.turno_id = "00000000-0000-0000-0000-000000000002"
        self.agora_utc = None


class _Runtime:
    def __init__(self, ctx: _Ctx, state: dict[str, Any] | None = None) -> None:
        self.context = ctx
        self.state = state if state is not None else {}


async def test_enviar_pin_nao_enfileira_loc_pin(monkeypatch: Any) -> None:
    """Mesmo com enviar_pin=True, nenhum job card:loc_pin e enfileirado (renderer NotImplemented)."""

    async def _fake_idempotente(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"enviar_pin": True, "mensagem": "ok"}

    monkeypatch.setattr(extracao, "_executar_idempotente", _fake_idempotente)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    out = await _chamar(
        proxima_acao_esperada="confirmar saida do cliente",
        runtime=_Runtime(_Ctx(redis)),
    )

    assert out == "ok"
    assert not any(c.kwargs.get("tipo") == "loc_pin" for c in redis.enqueue_job.call_args_list)


async def test_proxima_acao_longa_e_truncada_sem_erro(monkeypatch: Any) -> None:
    """Feedback piloto 21/07: >240 chars em proxima_acao_esperada estourava a validacao do
    tool-call e forcava retry (ruido recorrente). Agora o excesso e truncado no corpo da tool —
    nota interna, cortar nao perde nada critico."""
    capturado: dict[str, Any] = {}

    async def _fake_idempotente(
        _conn: Any, _turno: Any, _nome: Any, _seq: Any, dados: Any, **_kw: Any
    ) -> dict[str, Any]:
        capturado["dados"] = dados
        return {"mensagem": "ok"}

    monkeypatch.setattr(extracao, "_executar_idempotente", _fake_idempotente)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    out = await _chamar(
        proxima_acao_esperada="x" * 500,
        runtime=_Runtime(_Ctx(redis)),
    )

    assert out == "ok"
    assert len(capturado["dados"]["proxima_acao_esperada"]) == 240


async def test_par_preco_duracao_invalido_vira_toolexception(monkeypatch: Any) -> None:
    """Guarda do par preco x duracao (feedback piloto 21/07): a excecao do dominio vira erro
    recuperavel que instrui a IA a re-cotar pela tabela, sem crashar o turno."""

    async def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ParPrecoDuracaoInvalido

    monkeypatch.setattr(extracao, "_executar_idempotente", _raise)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    with pytest.raises(ToolException, match=r"^ERRO:.*duração"):
        await _chamar(
            proxima_acao_esperada="fechar 3h com o cliente",
            duracao_horas=3,
            runtime=_Runtime(_Ctx(redis)),
        )


async def test_antecedencia_insuficiente_vira_toolexception(monkeypatch: Any) -> None:
    """ADR 0025: AntecedenciaInsuficiente do domínio vira erro recuperável (ToolException) que
    instrui a IA a ancorar no <horario_minimo>, sem crashar o turno. Requer `horario_minimo` no
    State (há horário válido hoje); o ramo `None` está em test_antecedencia_horario_minimo.py."""

    async def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AntecedenciaInsuficiente("cedo demais")

    monkeypatch.setattr(extracao, "_executar_idempotente", _raise)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    state = {"horario_minimo": datetime(2026, 6, 25, 23, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))}
    with pytest.raises(ToolException, match=r"^ERRO:.*horario_minimo"):
        await _chamar(
            proxima_acao_esperada="confirmar horario",
            runtime=_Runtime(_Ctx(redis), state),
        )
