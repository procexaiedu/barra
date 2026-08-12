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

# Janela de voz/coalescencia do turno: `processar_turno` so ACORDA `DEFER_TURNO_S` depois do
# enqueue (9728a25, 22/07 — era 12s). Esta constante e a FONTE DE VERDADE do defer: tudo que o
# turno deferido precisa achar VIVO ao acordar deriva dela (os TTLs do debounce, via o teste de
# margem; o TTL do sinal de transcricao, via `ttl_sinal_transcricao_s`). Numero magico paralelo
# a este ja custou o apagao do audio: o defer subiu 15x e o TTL de 30s do canal
# `transcricao:{conversa_id}` ficou parado, entao TODO audio transcrito com sucesso virava a
# canned "nao consegui ouvir" — o sinal morria ~150s antes de o leitor acordar.
DEFER_TURNO_S = 180


def ttl_sinal_transcricao_s(defer_s: int = DEFER_TURNO_S) -> int:
    """TTL (s) do canal Redis `transcricao:{conversa_id}` (06 §1.4).

    Produtor e consumidor do sinal vivem em relogios diferentes: `transcrever_audio` faz o LPUSH
    poucos segundos depois de o audio chegar, mas quem faz o BLPOP e o `processar_turno`
    DEFERIDO — so `defer_s` depois. Por isso o prazo do sinal NAO pode ser constante propria: e
    funcao do defer, e mora ao lado dele para nao dessincronizar de novo.

    Piso em `TTL_PENDING`: enquanto a pendencia do turno estiver viva o turno ainda pode rodar
    (worker represado, deploy, retry do ARQ) e o sinal que ele vai ler precisa estar la; sinal
    que sobreviva a pendencia nao serve pra ninguem. O `defer_s + 120` cobre quem suba o defer
    acima do TTL do debounce sem mover os dois — o sinal continua cobrindo o proprio defer mais
    o orcamento do BLPOP (8s em `coordenador.aguardar_transcricoes`), com folga de jitter.
    """
    return max(TTL_PENDING, defer_s + 120)


async def enfileirar_processar_turno(
    arq: Any,
    conversa_id: str,
    *,
    aguardar_transcricao: bool = False,
    request_id: str | None = None,
    defer_s: int = DEFER_TURNO_S,
) -> None:
    """Enqueue de `processar_turno` com coalesce first-wins + fallback de varredura.

    O `_job_id` estatico (SET NX) coalesce o burst: o 1o enqueue vence e os seguintes
    devolvem None. Mas o ARQ tambem devolve None enquanto o job HOMONIMO esta RODANDO
    (a job_key so e deletada no finish_job, depois da coroutine retornar) — janela em que
    (a) o drain do coordenador pode ja ter passado pelo ultimo check de `pending` (corrida
    webhook x fim do job) e (b) o proprio coordenador nao consegue se re-enfileirar
    (MAX_DRAIN/LockBusy: a key e dele mesmo). Nesses casos o fallback de VARREDURA
    (`:varredura`, tambem SET NX — no maximo 1 na fila) garante um consumidor futuro do
    `pending`; se outro job consumir antes, o gate de pendencia do coordenador faz a
    varredura sair barata, sem invocar o grafo.

    A varredura vai com `aguardar_transcricao=False` de proposito: ela pode acabar
    processando uma mensagem diferente da que a originou, e esperar transcricao num turno
    de texto mandaria a canned de "nao consegui ouvir" ao cliente errado. Num turno de
    audio ela responde via janela (transcricao normalmente ja persistida ao rodar).
    """
    payload: dict[str, Any] = {
        "conversa_id": conversa_id,
        "request_id": request_id,
    }
    job = await arq.enqueue_job(
        "processar_turno",
        aguardar_transcricao=aguardar_transcricao,
        _job_id=f"turno:{conversa_id}",
        _defer_by=timedelta(seconds=defer_s),
        **payload,
    )
    if job is None:
        await arq.enqueue_job(
            "processar_turno",
            aguardar_transcricao=False,
            _job_id=f"turno:{conversa_id}:varredura",
            _defer_by=timedelta(seconds=defer_s + 2),
            **payload,
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
    o turno ja rodando e recuperado pelo drain loop do coordenador ou, na janela morta
    do fim do job, pelo fallback de varredura (`enfileirar_processar_turno`).

    `request_id` (OBS-07) viaja no payload do job p/ o coordenador bindar nos logs JSON.
    """
    cid = str(conversa_id)
    # 1. pendencia — lida pelo drain do coordenador (01 §4.3).
    await arq.set(chave_pending(cid), evolution_message_id, ex=TTL_PENDING)
    # 2. janela de debounce (TTL > a janela do `_defer_by`).
    await arq.set(chave_debounce(cid), evolution_message_id, ex=TTL_DEBOUNCE)
    # 3. coalesce via `_job_id` estatico (SET NX first-wins) + varredura.
    await enfileirar_processar_turno(
        arq,
        cid,
        aguardar_transcricao=aguardar_transcricao,
        request_id=request_id,
    )
