"""Coalesce + recuperação do turno (revisão LangGraph/ARQ 2026-06-09).

Cobre os dois lados do fix do re-enfileiramento perdido:

1. `enfileirar_processar_turno` (webhook/despacho.py): o ARQ devolve None tanto p/ job
   COALESCED (na fila) quanto p/ job HOMÔNIMO RODANDO (job_key só morre no finish_job).
   No None, o helper enfileira a VARREDURA (`turno:{cid}:varredura`) — antes disso, o
   MAX_DRAIN/LockBusy do coordenador re-enfileirava o PRÓPRIO job_id e o ARQ dropava em
   silêncio (turno perdido até a próxima mensagem do cliente).

2. Gate de pendência (workers/coordenador.py): a varredura pode rodar depois de outro job
   já ter consumido o pending; sem mensagem nova o coordenador NÃO invoca o grafo — a
   janela termina na fala da IA e o LLM emendaria outra bolha (double-texting).
"""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from fakeredis.aioredis import FakeRedis

from barra.webhook.despacho import enfileirar_processar_turno
from barra.workers.coordenador import processar_turno


class _ArqNX:
    """enqueue_job fiel ao SET NX do ARQ: devolve um objeto no 1º enqueue de cada _job_id
    e None nos seguintes (job na fila OU rodando — indistinguíveis p/ o caller)."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, Any]]] = []
        self._job_ids: set[str] = set()

    async def enqueue_job(self, name: str, **kwargs: Any) -> Any:
        job_id = kwargs["_job_id"]
        if job_id in self._job_ids:
            return None
        self._job_ids.add(job_id)
        self.enqueued.append((name, kwargs))
        return object()


async def test_enqueue_primario_vence_sem_varredura() -> None:
    arq = _ArqNX()
    cid = str(uuid4())
    await enfileirar_processar_turno(arq, cid, request_id="rid-1")

    assert len(arq.enqueued) == 1
    _, kwargs = arq.enqueued[0]
    assert kwargs["_job_id"] == f"turno:{cid}"
    assert kwargs["request_id"] == "rid-1"


async def test_enqueue_coalesced_cai_na_varredura() -> None:
    """Job homônimo já existe (fila ou rodando) -> o helper garante um consumidor futuro
    via varredura, sempre com aguardar_transcricao=False (pode processar mensagem diferente
    da que a originou; esperar transcrição num turno de texto mandaria canned errada)."""
    arq = _ArqNX()
    cid = str(uuid4())
    await enfileirar_processar_turno(arq, cid, aguardar_transcricao=True, request_id="rid-1")
    await enfileirar_processar_turno(arq, cid, aguardar_transcricao=True, request_id="rid-2")

    assert [k["_job_id"] for _, k in arq.enqueued] == [f"turno:{cid}", f"turno:{cid}:varredura"]
    varredura = arq.enqueued[1][1]
    assert varredura["aguardar_transcricao"] is False
    assert varredura["request_id"] == "rid-2"

    # 3º enqueue na mesma janela: primário E varredura já na fila -> nada novo (sem loop).
    await enfileirar_processar_turno(arq, cid, request_id="rid-3")
    assert len(arq.enqueued) == 2


class _GrafoContador:
    def __init__(self) -> None:
        self.chamadas = 0

    async def ainvoke(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        self.chamadas += 1
        return {"messages": []}


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


async def test_gate_de_pendencia_sem_mensagem_nova_nao_invoca_grafo(
    monkeypatch: Any,
) -> None:
    """Varredura/duplicado chegando depois de o pending ter sido consumido: retorna cedo,
    sem tocar o banco nem o grafo (db_pool=None explode se for usado)."""
    import barra.workers.coordenador as coord

    monkeypatch.setattr(coord, "adquirir_lock", _lock_noop)
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()
    graph = _GrafoContador()
    ctx: dict[str, Any] = {
        "redis": redis,
        "db_pool": None,
        "graph": graph,
        "settings": type("S", (), {"deepseek_model_chat": "deepseek-test"})(),
        "job_id": "job-varredura",
        "score": 1_700_000_000_000,
    }

    await processar_turno(ctx, conversa_id=str(uuid4()))

    assert graph.chamadas == 0
    redis.enqueue_job.assert_not_awaited()
