"""registrar_extracao: NAO enfileira o card loc_pin enquanto `_card_loc_pin` e NotImplemented.

Sem DB nem LLM: `_executar_idempotente` (o efeito de dominio) e mockado para devolver
`enviar_pin=True` (o caminho do atendimento interno qualificado), provando que mesmo com o
sinal ligado a tool nao enfileira `card:loc_pin` — o renderer em workers/envio.py ainda
levanta NotImplementedError e o job so falharia 5x. O `.coroutine` e a corrotina crua do @tool
(injeta o runtime fora do schema do LLM), espelhando test_consultar_agenda.py.
"""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import barra.agente.ferramentas.extracao as extracao
from barra.agente.ferramentas.extracao import ExtracaoPayload, registrar_extracao

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


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


async def test_enviar_pin_nao_enfileira_loc_pin(monkeypatch: Any) -> None:
    """Mesmo com enviar_pin=True, nenhum job card:loc_pin e enfileirado (renderer NotImplemented)."""

    async def _fake_idempotente(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"enviar_pin": True, "mensagem": "ok"}

    monkeypatch.setattr(extracao, "_executar_idempotente", _fake_idempotente)

    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()

    out = await _chamar(
        payload=ExtracaoPayload(proxima_acao_esperada="confirmar saida do cliente"),
        runtime=_Runtime(_Ctx(redis)),
    )

    assert out == "ok"
    assert not any(c.kwargs.get("tipo") == "loc_pin" for c in redis.enqueue_job.call_args_list)
