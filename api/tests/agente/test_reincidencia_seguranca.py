"""SEC-JB-02 — contador de reincidência por telefone no intercept_disclosure.

`_contabilizar_reincidencia` conta tentativas de disclosure/jailbreak por cliente em 24h e escala a
Fernando ao cruzar o limiar, 1x por janela, sem bloquear. Testado isolado com `abrir_handoff`
espiado (sem DB) e `FakeRedis` efêmero — o foco é o limiar + a idempotência por turno (replay).
"""

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.agente.contexto import ContextAgente

# `nos/__init__` reexporta a FUNÇÃO intercept_disclosure, que sombreia o submódulo de mesmo nome;
# `import ... as mod` pegaria a função. import_module devolve o módulo p/ monkeypatch (memória).
mod = importlib.import_module("barra.agente.nos.intercept_disclosure")
# `abrir_handoff` roda dentro de `_defesa.escalar_defesa` (saida de escala compartilhada): o spy
# troca o nome NAQUELE modulo.
mod_defesa = importlib.import_module("barra.agente._defesa")


class _DummyPool:
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[object]:
        yield object()


def _ctx(redis: FakeRedis, cliente_id: str, turno_id: str) -> ContextAgente:
    return ContextAgente(
        db_pool=_DummyPool(),  # type: ignore[arg-type]
        redis=redis,
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=cliente_id,
        turno_id=turno_id,
    )


@pytest.fixture
def spy_handoff(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    chamadas: list[dict[str, Any]] = []

    async def _spy(_conn: object, **kw: Any) -> None:
        chamadas.append(kw)

    monkeypatch.setattr(mod_defesa, "abrir_handoff", _spy)
    return chamadas


async def test_escala_ao_cruzar_o_limiar(spy_handoff: list[dict[str, Any]]) -> None:
    redis = FakeRedis()
    cid = str(uuid4())
    for i in range(3):  # limiar default = 3
        await mod._contabilizar_reincidencia(_ctx(redis, cid, f"turno-{i}"))
    assert len(spy_handoff) == 1  # só escala na 3a
    assert spy_handoff[0]["observacao"] == "reincidencia_seguranca"
    assert int(await redis.get(f"reincid:count:{cid}")) == 3


async def test_abaixo_do_limiar_nao_escala(spy_handoff: list[dict[str, Any]]) -> None:
    redis = FakeRedis()
    cid = str(uuid4())
    for i in range(2):
        await mod._contabilizar_reincidencia(_ctx(redis, cid, f"turno-{i}"))
    assert spy_handoff == []


async def test_replay_mesmo_turno_nao_duplica_contagem(spy_handoff: list[dict[str, Any]]) -> None:
    redis = FakeRedis()
    cid = str(uuid4())
    for _ in range(5):  # mesmo turno_id: re-drain do ARQ não pode contar 2x
        await mod._contabilizar_reincidencia(_ctx(redis, cid, "turno-fixo"))
    assert int(await redis.get(f"reincid:count:{cid}")) == 1
    assert spy_handoff == []


async def test_escala_uma_vez_por_janela(spy_handoff: list[dict[str, Any]]) -> None:
    redis = FakeRedis()
    cid = str(uuid4())
    for i in range(6):  # passa do limiar várias vezes, mas só 1 escalada na janela
        await mod._contabilizar_reincidencia(_ctx(redis, cid, f"turno-{i}"))
    assert len(spy_handoff) == 1


async def test_desligavel_por_flag(
    spy_handoff: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from barra.settings import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "reincidencia_seguranca_habilitada", False)
    redis = FakeRedis()
    cid = str(uuid4())
    for i in range(5):
        await mod._contabilizar_reincidencia(_ctx(redis, cid, f"turno-{i}"))
    assert spy_handoff == []
    assert await redis.get(f"reincid:count:{cid}") is None
