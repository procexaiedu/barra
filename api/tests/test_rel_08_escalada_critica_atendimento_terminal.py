"""REL-08 — um envio CRÍTICO que exauriu as retries nunca encerra sem handoff/alerta, mesmo
quando o atendimento aberto já virou terminal (`Fechado`/`Perdido`) entre o enqueue e a retry
final. Nesse caso `_carregar_destino` devolve `atendimento_id=NULL` (filtra terminais) e a escalada
(`escaladas.atendimento_id NOT NULL`) falharia em silêncio. O fix recupera o último atendimento da
conversa em qualquer estado; sem nenhum, alerta dedicado (log+Sentry) em vez de silêncio.

Reusa o estilo de fakes de `test_rel_12_falha_final_visivel.py`: Evolution que levanta no envio,
`_FakeConn`/`_FakePool`, Redis efêmero e `asyncio.sleep` neutralizado.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.workers import coordenador, envio
from barra.workers.envio import enviar_turno


@pytest.fixture(autouse=True)
def _sem_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop)
    yield


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, destino: dict[str, Any], atendimento_recente: dict[str, Any] | None) -> None:
        self._destino = destino
        self._atendimento_recente = atendimento_recente

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "FROM barravips.conversas" in query:
            return _Result([self._destino])
        if "FROM barravips.atendimentos" in query:
            return _Result([self._atendimento_recente] if self._atendimento_recente else [])
        return _Result([])

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


class _EvolutionExplode:
    """Marca a leitura como OK e levanta no envio do texto (efeito crítico já no banco, bolha não
    entregue)."""

    async def marcar_lida(self, **_: Any) -> None:
        return None

    async def set_presence(self, **_: Any) -> None:
        return None

    async def enviar_texto(self, **_: Any) -> str:
        raise RuntimeError("evolution 500")


def _destino_terminal() -> dict[str, Any]:
    # atendimento_id=None: `_carregar_destino` filtra terminais → o aberto virou Fechado/Perdido.
    return {
        "evolution_instance_id": "inst-1",
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": None,
    }


def _ctx(redis: FakeRedis, conn: _FakeConn) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": _FakePool(conn),
        "evolution": _EvolutionExplode(),
        "minio": None,
        "job_try": 3,
        "max_tries": 3,
        "job_id": "job-rel08",
    }


async def test_critico_exaurido_com_atendimento_terminal_ainda_escala(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """atendimento_id veio nulo (terminal), mas a conversa tem um atendimento recuperável →
    abre handoff nele, em vez de quebrar contra o NOT NULL."""
    turno_id, conversa_id = "turno-CRIT", str(uuid4())
    atendimento_recente = uuid4()

    chamadas: list[UUID] = []

    async def _fake_escalar(_pool: Any, atendimento_id: UUID, _turno: str, **_k: Any) -> None:
        chamadas.append(atendimento_id)

    monkeypatch.setattr(coordenador, "escalar_por_exaustao", _fake_escalar)

    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)
    conn = _FakeConn(_destino_terminal(), {"id": atendimento_recente})

    with pytest.raises(RuntimeError, match="evolution 500"):
        await enviar_turno(
            _ctx(redis, conn),
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=["card crítico"],
            midias=[],
            msg_ids_cliente=[],
            chars_inbound=0,
            critico=True,
        )

    # Escalou no atendimento recuperado (qualquer estado), não em None.
    assert chamadas == [atendimento_recente]


async def test_critico_exaurido_sem_atendimento_alerta_dedicado(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Conversa sem nenhum atendimento: não dá para abrir handoff, mas a perda do efeito crítico
    não pode ser silenciosa — log dedicado + captura no Sentry."""
    turno_id, conversa_id = "turno-CRIT2", str(uuid4())

    chamadas: list[UUID] = []

    async def _fake_escalar(_pool: Any, atendimento_id: UUID, _turno: str, **_k: Any) -> None:
        chamadas.append(atendimento_id)

    monkeypatch.setattr(coordenador, "escalar_por_exaustao", _fake_escalar)

    capturas: list[str] = []
    monkeypatch.setattr(
        envio,
        "sentry_sdk",
        SimpleNamespace(capture_exception=lambda *a, **k: capturas.append("captured")),
    )

    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)
    conn = _FakeConn(_destino_terminal(), None)

    with caplog.at_level(logging.ERROR, logger="barra.workers.envio"):
        with pytest.raises(RuntimeError, match="evolution 500"):
            await enviar_turno(
                _ctx(redis, conn),
                conversa_id=conversa_id,
                turno_id=turno_id,
                chunks=["card crítico"],
                midias=[],
                msg_ids_cliente=[],
                chars_inbound=0,
                critico=True,
            )

    # Sem atendimento não escala...
    assert chamadas == []
    # ...mas não silencia: Sentry + log dedicado com turno_id e conversa_id.
    assert capturas == ["captured"]
    erros = [r for r in caplog.records if r.levelno == logging.ERROR]
    msgs = [r.getMessage() for r in erros]
    assert any(
        "envio_critico_sem_atendimento" in m and turno_id in m and conversa_id in m for m in msgs
    )
