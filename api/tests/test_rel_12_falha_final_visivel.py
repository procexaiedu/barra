"""REL-12 — uma falha FINAL não-crítica de envio (mensagem perdida ao cliente) deixa de ser
silenciosa: loga `error` com `turno_id`+`request_id` (= job_id do ARQ) e captura no Sentry, sem
mudar a entrega/retry.

Reusa o estilo de fakes de `integracao/test_enviar_turno.py`: Evolution mockado, `_FakeConn`/
`_FakePool` respondem `_carregar_destino`, Redis efêmero (fakeredis) e `asyncio.sleep` neutralizado.
Aqui o Evolution LEVANTA no envio do texto, com `job_try == max_tries` e `critico=False`, forçando
o ramo de falha final não-crítica.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from barra.workers import envio
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
    def __init__(self, destino: dict[str, Any]) -> None:
        self._destino = destino

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "FROM barravips.conversas" in query:
            return _Result([self._destino])
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
    """Marca a leitura como OK e levanta no envio do texto (falha de entrega ao cliente)."""

    async def marcar_lida(self, **_: Any) -> None:
        return None

    async def set_presence(self, **_: Any) -> None:
        return None

    async def enviar_texto(self, **_: Any) -> str:
        raise RuntimeError("evolution 500")


def _destino() -> dict[str, Any]:
    return {
        "evolution_instance_id": "inst-1",
        "evolution_chat_id": "5521999@s.whatsapp.net",
        "atendimento_id": uuid4(),
    }


def _ctx(redis: FakeRedis, *, job_try: int, max_tries: int, job_id: str) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": _FakePool(_FakeConn(_destino())),
        "evolution": _EvolutionExplode(),
        "minio": None,
        "job_try": job_try,
        "max_tries": max_tries,
        "job_id": job_id,
    }


async def test_falha_final_nao_critica_loga_e_captura_no_sentry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    turno_id, conversa_id, job_id = "turno-FAIL", str(uuid4()), "job-abc-123"

    capturas: list[str] = []
    monkeypatch.setattr(
        envio,
        "sentry_sdk",
        SimpleNamespace(capture_exception=lambda *a, **k: capturas.append("captured")),
    )

    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    with caplog.at_level(logging.ERROR, logger="barra.workers.envio"):
        with pytest.raises(RuntimeError, match="evolution 500"):
            await enviar_turno(
                _ctx(redis, job_try=5, max_tries=5, job_id=job_id),
                conversa_id=conversa_id,
                turno_id=turno_id,
                chunks=["oi amor"],
                midias=[],
                msg_ids_cliente=[],
                chars_inbound=0,
                critico=False,
            )

    # 1. Sentry capturou a exceção (visibilidade à operação).
    assert capturas == ["captured"]

    # 2. Log `error` com turno_id + request_id (= job_id).
    erros = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert erros, "esperava ao menos um log ERROR"
    msg = erros[-1].getMessage()
    assert turno_id in msg
    assert job_id in msg
    assert "request_id" in msg


async def test_falha_nao_final_nao_captura_no_sentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Antes do teto de tentativas (job_try < max_tries) o ARQ ainda vai retentar: a falha
    re-propaga SEM virar log final/Sentry — preserva a semântica de retry."""
    turno_id, conversa_id = "turno-RETRY", str(uuid4())

    capturas: list[str] = []
    monkeypatch.setattr(
        envio,
        "sentry_sdk",
        SimpleNamespace(capture_exception=lambda *a, **k: capturas.append("captured")),
    )

    redis = FakeRedis()
    await redis.set(f"turno_atual:{conversa_id}", turno_id)

    with pytest.raises(RuntimeError, match="evolution 500"):
        await enviar_turno(
            _ctx(redis, job_try=1, max_tries=5, job_id="job-xyz"),
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunks=["oi amor"],
            midias=[],
            msg_ids_cliente=[],
            chars_inbound=0,
            critico=False,
        )

    assert capturas == []  # ainda há retry pela frente: não captura como falha final
