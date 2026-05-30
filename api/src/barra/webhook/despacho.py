"""Enfileira o turno do coordenador a partir do webhook (01 §4.2).

O webhook nao roda o turno: so marca pendencia/debounce e enfileira `processar_turno`.
Quem resolve/cria o atendimento e o coordenador (`workers/coordenador.py`), sob `lock:conv`.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from barra.webhook.debounce import (
    TTL_DEBOUNCE,
    TTL_PENDING,
    chave_debounce,
    chave_pending,
)


async def enfileirar_turno(
    arq: Any,
    conversa_id: UUID,
    evolution_message_id: str,
    *,
    aguardar_transcricao: bool = False,
    request_id: str | None = None,
) -> None:
    """Marca pendencia + debounce e enfileira `processar_turno` (01 §4.2).

    `arq` e a ArqRedis (a mesma conexao do coordenador — expoe `set`/`enqueue_job`).
    O `_job_id` estatico e o coalesce first-wins: o ARQ faz SET NX, o 1o vence e os
    enqueues seguintes na janela sao DESCARTADOS — nao ha substituicao. Quem chega com
    o turno ja rodando e recuperado pelo drain loop do coordenador, nao por reenfileiramento.

    `request_id` (OBS-07) viaja no payload do job p/ o coordenador bindar nos logs JSON.
    """
    cid = str(conversa_id)
    # 1. pendencia — lida pelo drain do coordenador (01 §4.3).
    await arq.set(chave_pending(cid), evolution_message_id, ex=TTL_PENDING)
    # 2. janela de debounce (TTL > a janela do `_defer_by`).
    await arq.set(chave_debounce(cid), evolution_message_id, ex=TTL_DEBOUNCE)
    # 3. coalesce via `_job_id` estatico (SET NX first-wins).
    await arq.enqueue_job(
        "processar_turno",
        conversa_id=cid,
        aguardar_transcricao=aguardar_transcricao,
        request_id=request_id,
        _job_id=f"turno:{cid}",
        _defer_by=timedelta(seconds=4),
    )
