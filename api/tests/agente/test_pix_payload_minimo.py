"""WIN-TOOLS-09: o payload Pix persistido tem SÓ `valor` — sem chave/titular em claro.

Guard-rail de dado sensível (CONTEXT.md "Pix de deslocamento"): a chave e o titular do Pix
NUNCA vão em claro para `tool_calls`/`eventos`. A tool `pedir_pix_deslocamento` constrói UM
único dict de payload que serve tanto o `tool_calls` (via `_executar_idempotente`) quanto o
evento `pix_solicitado` (via o executor) — capturar esse dict na fronteira de persistência
prova os dois de uma vez.

Sem DB e sem chave: o SELECT da chave/titular da modelo é fingido e `_executar_idempotente`
é monkeypatchado p/ capturar o payload sem rodar o executor (que tocaria o banco).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from barra.agente.ferramentas import pix
from barra.agente.ferramentas.pix import pedir_pix_deslocamento
from barra.settings import get_settings

# .coroutine é a corrotina crua do @tool; .ainvoke({...}) NÃO injeta runtime, .coroutine sim.
_chamar = pedir_pix_deslocamento.coroutine  # type: ignore[attr-defined]


class _FakeResult:
    async def fetchone(self) -> dict[str, Any]:
        return {"chave_pix": "chave-secreta-da-modelo", "titular_chave": "Fulana de Tal"}


class _FakeConn:
    async def execute(self, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult()


class _PoolFake:
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield _FakeConn()


class _Ctx:
    def __init__(self, pool: Any) -> None:
        self.db_pool = pool
        self.atendimento_id = "00000000-0000-0000-0000-000000000001"
        self.modelo_id = "00000000-0000-0000-0000-000000000002"
        self.turno_id = "00000000-0000-0000-0000-000000000003"


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


async def test_payload_persistido_so_tem_valor(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    async def _fake_idempotente(
        conn: Any,
        turno_id: str,
        tool_name: str,
        call_idx: int,
        payload: dict[str, Any],
        executor: Any,
    ) -> dict[str, Any]:
        capturado["payload"] = payload
        return {}

    monkeypatch.setattr(pix, "_executar_idempotente", _fake_idempotente)

    out = await _chamar(runtime=_Runtime(_Ctx(_PoolFake())))

    assert "solicitado" in out  # caminho feliz (não ERRO)
    payload = capturado["payload"]
    # valor vem da setting (fonte unica), serializado como string decimal.
    assert payload == {"valor": str(get_settings().pix_deslocamento_valor)}
    assert "chave" not in payload
    assert "titular" not in payload
