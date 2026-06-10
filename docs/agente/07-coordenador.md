# 07 — Coordenador de Turno e Cron de Timeouts

> Worker `processar_turno` (lock Redis, debounce, drain bounded, resolução determinística, exaustão) e crons determinísticos (`timeouts.py` + `confirmar_em_execucao` + `limpar_midias`).
>
> **Status (2026-06-10):** crons **e** `processar_turno` (`workers/coordenador.py`) estão **implementados**. §2/§3 nasceram como spec e o código evoluiu além delas em dois pontos: o `turno_id` inclui o `score` (`uuid5(job_id:score:loop_idx)` — o `_job_id` estático por conversa colidia turnos distintos) e o coalesce ganhou fallback de varredura (`turno:{cid}:varredura`, `despacho.py`, 2026-06-09). Decisões em `[[decisoes_grilling_23-05_coordenador]]`.

## 1. Por que ARQ e não inline no webhook

Webhook tem timeout do Evolution (~15s). Turno de IA com 5+ tool calls + Sonnet 4.6 pode passar de 8s. Inline arrisca:
- Webhook responder 504 → Evolution retentar → segunda mensagem persistida.
- Bloqueio do event loop FastAPI.

Worker ARQ desacopla: webhook responde 200 imediatamente após persistir + enfileirar; turno roda em processo separado, retries idempotentes via `turno_id` determinístico (`01 §6.7`). O bound de tempo do turno **não** é o `job_timeout` do ARQ (rede externa, generoso) e sim **teto de drain + `asyncio.wait_for(graph, 60s)` por iteração** (§3).

## 2. Estrutura do worker

`workers/settings.py` já existe (hoje só com os crons; `functions=[]`). Ganha as funções de job quando `coordenador.py` + os jobs de envio/mídia/pix forem construídos. Alvo (espelha o estilo shipado: funções de módulo + wrappers de cron):

```python
# api/src/barra/workers/settings.py
from typing import Any, ClassVar
from arq import cron
from arq.connections import RedisSettings
from arq.cron import CronJob

from barra.core.db import criar_pool, fechar_pool
from barra.core.evolution import EvolutionClient
from openai import AsyncOpenAI                          # vision do Pix via OpenRouter (cliente OpenAI-compat)
from barra.core.storage import criar_minio
from barra.settings import Settings, get_settings
from barra.agente.graph import build_graph

from barra.workers.media import limpar_midias_vencidas
from barra.workers.timeouts import (
    aplicar_timeout_interno, aplicar_timeout_longo, confirmar_em_execucao,
)
from barra.workers.coordenador import processar_turno          # NOVO (07)
from barra.workers.envio import enviar_turno, enviar_card      # NOVO (05)
from barra.workers.media import transcrever_audio, rotear_imagem  # NOVO (06)
from barra.workers.pix import validar_pix                      # NOVO (06)


# wrappers de cron: pegam conn do pool e delegam à função pura (testável sem DB)
async def cron_timeout_longo(ctx):     return await _run(ctx, aplicar_timeout_longo)
async def cron_timeout_interno(ctx):   return await _run(ctx, aplicar_timeout_interno)
async def cron_confirmar(ctx):         return await _run(ctx, confirmar_em_execucao)

async def _run(ctx, fn):
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await fn(conn)

async def cron_limpar_midias(ctx):
    pool, minio = ctx.get("db_pool"), ctx.get("minio")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await limpar_midias_vencidas(conn, minio)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    # criar_pool ESTENDIDO p/ aceitar max_size/autocommit (defaults atuais preservados p/ a API).
    # Mantém configure=_configurar_conexao (prepare_threshold=None) — OBRIGATÓRIO no Supavisor
    # transaction mode / ADR-0002. NUNCA inlinar um AsyncConnectionPool aqui (esqueceria o configure).
    ctx["db_pool"] = await criar_pool(settings.database_url, max_size=20, autocommit=True)
    ctx["minio"] = criar_minio(settings)
    ctx["evolution"] = EvolutionClient(settings)               # construtor real é (settings)
    ctx["vision_client"] = AsyncOpenAI(                          # vision do Pix via OpenRouter (06 §2.3/§0 item 4)
        api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1",
    )
    ctx["graph"] = build_graph()                               # SEM checkpointer no P0 (01 §6.7)
    # NÃO criar ctx["redis"]: o ARQ já injeta a ArqRedis em ctx["redis"] ANTES do startup. Ela é
    # subclasse de redis.asyncio.Redis → serve p/ lock/dedupe/pending/BLPOP E enqueue_job.
    # Sobrescrever com cliente puro (criar_redis) mataria enqueue_job — bug da versão anterior.

async def shutdown(ctx: dict[str, Any]) -> None:
    await fechar_pool(ctx.get("db_pool"))
    if (client := ctx.get("vision_client")) is not None:
        await client.close()

def _redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url) if settings.redis_url else RedisSettings()

_settings = get_settings()


class WorkerSettings:
    """Configuração ARQ. Usar: `arq barra.workers.settings.WorkerSettings`."""

    redis_settings = _redis_settings(_settings)
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = [
        processar_turno,                          # 07
        enviar_turno, enviar_card,                # 05
        transcrever_audio, rotear_imagem, validar_pix,  # 06
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(cron_timeout_interno, name="timeout_interno"),             # a cada minuto
        cron(cron_confirmar, name="confirmar_em_execucao"),            # a cada minuto
        cron(cron_timeout_longo, name="timeout_longo",
             minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),   # a cada 5 min
        cron(cron_limpar_midias, name="limpar_midias", hour={3}, minute={0}),  # diário 03:00
    ]
    max_jobs = 10        # 2× folga sobre o pool (max_size=20) p/ turno+envio+media+pix concorrentes
    job_timeout = 400    # só a rede externa: cobre MAX_DRAIN × (60s graph + 8s transcrição + overhead)
    keep_result = 3600   # ATENÇÃO: NÃO vale p/ processar_turno — ver nota abaixo
```

> **`keep_result=0` para `processar_turno` (auditoria 2026-05-23 — bug que perde mensagens em silêncio).** O `keep_result=3600` global **quebra o re-enqueue do drain** (passo do `else`/`MAX_DRAIN` em `§3`) e o coalescing do `_job_id` estático `turno:{conversa_id}`. Confirmado por issues do ARQ (#416, #432): re-enfileirar um `_job_id` cuja chave `arq:in-progress` ou **`result`** ainda existe faz `enqueue_job` **retornar `None` silenciosamente**. Com `keep_result=3600`, a `result` key bloqueia o re-enqueue do mesmo `_job_id` por **1 hora após o término** — então o trabalho restante do drain é perdido sem erro, e mensagens novas da conversa nessa janela podem ser descartadas. **Correção:** `processar_turno` deve ter `keep_result=0` (via `@func(keep_result=0)` ou config por-função — ninguém lê o resultado do turno). Manter `keep_result` alto só p/ jobs cujo resultado é lido. **Adicionar teste de integração** que estoura `MAX_DRAIN` e afirma que o restante roda.

> **Windows (dev local):** o worker usa psycopg async; em Windows exige `WindowsSelectorEventLoopPolicy` antes de subir o loop, senão dá `PoolTimeout`. Produção é Linux (Portainer). Ver `[[backend-windows-selector-loop]]`.

## 3. `processar_turno` — implementação completa

```python
# api/src/barra/workers/coordenador.py
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from langgraph.errors import GraphRecursionError
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from barra.agente.contexto import ContextAgente   # Runtime Context API (04 §1.1) — injetado via context=
from barra.workers._chunking import chunk_texto

# Namespace fixo do módulo para turno_id determinístico (01 §6.7). NUNCA uuid7() runtime —
# o retry do ARQ regeneraria turno_id novo, furaria as dedupe de envio e duplicaria a resposta.
NS_TURNO = UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")


ESTADOS_TERMINAIS = {"Fechado", "Perdido"}
MAX_DRAIN = 5            # teto de iterações de drain sob o MESMO lock; ao estourar, re-enfileira
RECURSION_LIMIT = 18     # ~6-7 round-trips llm↔tools (5 tools no P0). DORMENTE no skeleton linear


async def processar_turno(
    ctx: dict,
    *,
    conversa_id: str,
    aguardar_transcricao: bool = False,
) -> None:
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    graph = ctx["graph"]
    settings = ctx["settings"]

    # O lock contende SÓ com rotear_imagem (06 §2.1). Ocupado → re-defere curto; pending já
    # foi setado por enfileirar_turno, então ao re-disparar o turno lê a janela inteira.
    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            for loop_idx in range(MAX_DRAIN):  # DRAIN LOOP BOUNDED (01 §4.3): msgs com o lock retido
                # turno_id DETERMINÍSTICO por (job, iteração) — o retry do ARQ reusa as dedupe keys
                # de envio/tool → sem resposta duplicada (01 §6.7). NUNCA uuid7() runtime.
                turno_id = str(uuid5(NS_TURNO, f"{ctx['job_id']}:{loop_idx}"))
                await redis.delete(f"pending:conv:{conversa_id}")  # limpa ANTES de ler a janela

                # 1. resolver atendimento e cobrir órfãs
                async with pool.connection() as conn, conn.transaction():
                    atendimento = await resolver_atendimento(conn, UUID(conversa_id))
                    await atualizar_orfaos(conn, UUID(conversa_id), atendimento["id"])
                    await registrar_evento_turno_iniciado(conn, atendimento["id"], turno_id)

                # 2. gates (ia_pausada OU estado terminal → encerra)
                if atendimento["ia_pausada"] or atendimento["estado"] in ESTADOS_TERMINAIS:
                    logger.info("turno_skipped", conversa_id=conversa_id, estado=atendimento["estado"])
                    TURNO_RESULTADO.labels("ia_pausada_skip").inc()
                    break

                if aguardar_transcricao:
                    # canal keyed por conversa_id (06 §1.4) — atendimento_id seria racy (mensagem órfã)
                    ok = await aguardar_transcricoes(redis, conversa_id, timeout=8)
                    if not ok:
                        logger.warning("transcricao_timeout", conversa_id=conversa_id)
                        TURNO_RESULTADO.labels("transcricao_timeout").inc()
                        # segue mesmo assim com placeholder

                # 3. marca o turno atual — ISTO É o cancel-on-new-message (05 §3.1): o job
                #    enviar_turno do turno anterior compara turno_atual e aborta os chunks
                #    pendentes ao detectar que foi superado (turno crítico ignora o check).
                await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)

                # 4. monta config + context (o contexto é montado dentro do grafo, pelo prepare_context — 03 §7).
                #    Runtime Context API (04 §1.1): deps/IDs vão no ContextAgente via context=; só thread_id
                #    e recursion_limit ficam no config (nativos do LangGraph). conversa_id == thread_id, e
                #    settings é bindado no build_graph (03 §6.4) — nenhum dos dois entra no context por-turno.
                config = {
                    "configurable": {"thread_id": conversa_id},
                    "recursion_limit": RECURSION_LIMIT,
                }
                context = ContextAgente(
                    db_pool=pool,
                    redis=redis,
                    modelo_id=str(atendimento["modelo_id"]),
                    atendimento_id=str(atendimento["id"]),
                    cliente_id=str(atendimento["cliente_id"]),
                    turno_id=turno_id,
                )
                entrada = {"messages": []}  # prepare_context monta persona+regras+FAQ+programas+dinâmico+janela

                # 5. invoca grafo
                inicio = asyncio.get_event_loop().time()
                try:
                    resultado = await asyncio.wait_for(
                        graph.ainvoke(entrada, config=config, context=context),
                        timeout=60.0,
                    )
                except asyncio.TimeoutError:
                    logger.error("graph_timeout", turno_id=turno_id)
                    await escalar_por_exaustao(pool, atendimento["id"], turno_id, motivo="timeout_grafo")
                    TURNO_RESULTADO.labels("exaustao").inc()
                    break
                except GraphRecursionError:
                    # captura por CLASSE, não string-match: robusto a mudança de msg da lib
                    # (decisão 2026-05-23). DORMENTE no skeleton: o grafo é LINEAR (graph.py,
                    # prepare→intercept→llm→tools→post_process); só dispara com o loop llm↔tools de M1.
                    await escalar_por_exaustao(pool, atendimento["id"], turno_id, motivo="exaustao_iteracoes")
                    TURNO_RESULTADO.labels("exaustao").inc()
                    break
                except Exception:
                    logger.exception("graph_erro", turno_id=turno_id)
                    raise
                finally:
                    TURNO_DURACAO.observe(asyncio.get_event_loop().time() - inicio)

                # 6. cinto-suspensório (01 §6.10): ia_pausada OU estado terminal → descarta texto
                async with pool.connection() as conn:
                    res = await conn.execute(
                        "SELECT ia_pausada, estado FROM barravips.atendimentos WHERE id = %s",
                        (atendimento["id"],),
                    )
                    pos = await res.fetchone()
                if pos["ia_pausada"] or pos["estado"] in ESTADOS_TERMINAIS:
                    logger.info("turno_descartado", atendimento_id=atendimento["id"])
                    TURNO_RESULTADO.labels("escalado").inc()
                else:
                    # 7. extrai resposta + mídias + msgs do cliente do turno (p/ read receipt, 05 §4.2)
                    ai_final = next(
                        m for m in reversed(resultado["messages"]) if isinstance(m, AIMessage)
                    )
                    texto = ai_final.content or ""
                    async with pool.connection() as conn:
                        res = await conn.execute(
                            """
                            SELECT payload->>'midia_id' AS midia_id, payload->>'legenda' AS legenda
                              FROM barravips.tool_calls
                             WHERE turno_id = %s AND tool_name = 'enviar_midia'
                             ORDER BY call_idx
                            """,
                            (turno_id,),
                        )
                        midias = await res.fetchall()
                        # msgs do cliente AINDA NÃO respondidas (desde a última msg da IA): é a
                        # janela que este turno responde → marcar como lidas no enviar_turno (05 §4.2).
                        res = await conn.execute(
                            """
                            SELECT evolution_message_id, conteudo
                              FROM barravips.mensagens
                             WHERE conversa_id = %s AND direcao = 'cliente'
                               AND evolution_message_id IS NOT NULL
                               AND created_at > COALESCE(
                                     (SELECT max(created_at) FROM barravips.mensagens
                                       WHERE conversa_id = %s AND direcao = 'ia'), 'epoch')
                             ORDER BY created_at
                            """,
                            (conversa_id, conversa_id),
                        )
                        inbound = await res.fetchall()
                    msg_ids_cliente = [r["evolution_message_id"] for r in inbound]
                    chars_inbound = sum(len(r["conteudo"] or "") for r in inbound)

                    chunks = chunk_texto(texto)
                    if not chunks and not midias:
                        logger.warning("turno_sem_resposta", turno_id=turno_id)
                        TURNO_RESULTADO.labels("ok_sem_resposta").inc()
                    else:
                        # 8. turno é CRÍTICO se houve write tool COM EFEITO (05 §3): a msg
                        #    (ex.: chave Pix) não pode ser cancelada nem perdida. pedir_pix OU
                        #    registrar_extracao que CAUSOU transição (marcar todo registrar_extracao
                        #    mataria o cancel). O flag vai no PAYLOAD do job (05 §7) — não no Redis,
                        #    cujo TTL pode expirar antes da última retry com backoff.
                        async with pool.connection() as conn:
                            res = await conn.execute(
                                """
                                SELECT 1 FROM barravips.tool_calls
                                 WHERE turno_id = %s
                                   AND ( tool_name = 'pedir_pix_deslocamento'
                                      OR (tool_name = 'registrar_extracao' AND resultado->>'novo_estado' IS NOT NULL) )
                                 LIMIT 1
                                """,
                                (turno_id,),
                            )
                            critico = await res.fetchone() is not None

                        await despachar_humanizacao(
                            ctx, conversa_id, turno_id, chunks, midias,
                            msg_ids_cliente, chars_inbound, critico,
                        )

                        # 9. métricas de tokens. No langchain-anthropic 1.x os contadores de cache
                        #    vivem em usage_metadata["input_token_details"] (cache_read/cache_creation),
                        #    NÃO em response_metadata["usage"]["cache_*"] (formato do raw SDK). Ler do
                        #    caminho errado mede cache como ZERO em silêncio (auditoria 2026-05-23, 03 §4.2).
                        um = getattr(ai_final, "usage_metadata", None) or {}
                        det = um.get("input_token_details", {})
                        TURNO_TOKENS.labels("input").inc(um.get("input_tokens", 0))
                        TURNO_TOKENS.labels("output").inc(um.get("output_tokens", 0))
                        TURNO_TOKENS.labels("cache_read").inc(det.get("cache_read", 0))
                        TURNO_TOKENS.labels("cache_write").inc(det.get("cache_creation", 0))
                        TURNO_RESULTADO.labels("ok").inc()

                # 10. drena: chegou msg com o lock retido? re-roda sob o MESMO lock; senão sai
                if not await redis.get(f"pending:conv:{conversa_id}"):
                    break
            else:
                # teto de drain (MAX_DRAIN) estourado com pending ainda cheio → re-enfileira
                # (libera o lock). Evita prender um worker slot num cliente tagarela.
                if await redis.get(f"pending:conv:{conversa_id}"):
                    await redis.enqueue_job(
                        "processar_turno",
                        conversa_id=conversa_id,
                        aguardar_transcricao=False,
                        _job_id=f"turno:{conversa_id}",
                        _defer_by=timedelta(seconds=2),
                    )
    except LockBusy:
        # contenda com rotear_imagem (06 §2.1) — re-defere curto via ctx["redis"] (ArqRedis)
        await redis.enqueue_job(
            "processar_turno",
            conversa_id=conversa_id,
            aguardar_transcricao=aguardar_transcricao,
            _job_id=f"turno:{conversa_id}",
            _defer_by=timedelta(seconds=2),
        )
        LOCK_OCUPADO.inc()
```

### 3.1 Lock Redis com heartbeat

```python
# api/src/barra/core/redis.py — helper
@asynccontextmanager
async def adquirir_lock(redis: Redis, chave: str, *, ttl: int, heartbeat_interval: int):
    """Tenta SETNX; se ocupado, levanta LockBusy.

    Inicia task que renova TTL periodicamente enquanto o lock estiver ativo.
    """
    token = secrets.token_hex(8)
    ok = await redis.set(chave, token, nx=True, ex=ttl)
    if not ok:
        raise LockBusy(chave)

    cancelar = asyncio.Event()

    async def heartbeat():
        while not cancelar.is_set():
            try:
                await asyncio.wait_for(cancelar.wait(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                # verifica que ainda somos donos antes de estender
                atual = await redis.get(chave)
                if atual != token:
                    cancelar.set()
                    return
                await redis.expire(chave, ttl)

    hb_task = asyncio.create_task(heartbeat())
    try:
        yield
    finally:
        cancelar.set()
        await hb_task
        # release condicional via Lua script (segurança)
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1, chave, token,
        )
```

### 3.2 Resolução determinística do atendimento

```python
async def resolver_atendimento(conn, conversa_id: UUID) -> dict:
    """Busca atendimento aberto da conversa; cria em Novo se não houver."""
    res = await conn.execute(
        """
        SELECT a.*
          FROM barravips.atendimentos a
         WHERE a.conversa_id = %s
           AND a.estado NOT IN ('Fechado', 'Perdido')
         ORDER BY a.created_at DESC
         LIMIT 1
         FOR UPDATE OF a
        """,
        (conversa_id,),
    )
    row = await res.fetchone()
    if row:
        return row

    # Cria novo atendimento
    res = await conn.execute(
        """
        INSERT INTO barravips.atendimentos
          (cliente_id, modelo_id, conversa_id, estado, fonte_decisao_ultima_transicao)
        SELECT cliente_id, modelo_id, id, 'Novo', 'extracao_ia'
          FROM barravips.conversas WHERE id = %s
        RETURNING *
        """,
        (conversa_id,),
    )
    return await res.fetchone()


async def atualizar_orfaos(conn, conversa_id: UUID, atendimento_id: UUID) -> None:
    """Vincula mensagens órfãs (atendimento_id=NULL) ao atendimento corrente."""
    await conn.execute(
        """
        UPDATE barravips.mensagens
           SET atendimento_id = %s
         WHERE conversa_id = %s AND atendimento_id IS NULL
        """,
        (atendimento_id, conversa_id),
    )
```

### 3.3 Escalada por exaustão

```python
async def escalar_por_exaustao(
    pool: AsyncConnectionPool,
    atendimento_id: UUID,
    turno_id: str,
    motivo: str = "exaustao_iteracoes",
) -> None:
    """Abre handoff para Fernando sem mensagem ao cliente."""
    from barra.dominio.escaladas.service import abrir_handoff

    async with pool.connection() as conn:
        await abrir_handoff(
            conn,
            atendimento_id=atendimento_id,
            responsavel="Fernando",
            motivo=motivo,
            resumo_operacional=(
                f"Agente não encerrou o turno: estourou recursion_limit "
                f"({RECURSION_LIMIT} super-steps ≈ {RECURSION_LIMIT // 2} round-trips) ou excedeu 60s. "
                f"turno_id={turno_id}. Verificar trace LangSmith."
            ),
            acao_esperada="Revisar trace, decidir se devolve para IA ou assume manualmente.",
            origem="agente",
            autor="sistema",
        )
```

### 3.4 Despacho da humanização

**Um único job** `enviar_turno` por turno (05 §1): ele percorre chunks e mídias em ordem, com
cancel/dedupe checados entre os itens dentro do mesmo processo. Jobs por chunk não garantiriam
ordem (`max_jobs` deixa rodar concorrente).

```python
async def despachar_humanizacao(
    ctx,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict],
    msg_ids_cliente: list[str],
    chars_inbound: int,
    critico: bool,
) -> None:
    arq = ctx["redis"]  # em ARQ, ctx["redis"] é a ArqRedis e expõe enqueue_job
    await arq.enqueue_job(
        "enviar_turno",
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=chunks,
        midias=midias,
        msg_ids_cliente=msg_ids_cliente,   # read receipt + reading delay (05 §4.2)
        chars_inbound=chars_inbound,
        critico=critico,
        _job_id=f"turno_envio:{turno_id}",   # dedupe nativo do ARQ
    )
```

## 4. Crons determinísticos (implementados)

`workers/timeouts.py` + `workers/media.py:limpar_midias_vencidas` são **SQL puro/atômico** (ADR-0002), disparados pelos wrappers de cron da §2. O `reengajar_silenciosos` (§4.5) é o único que **envia ao cliente** — os demais só mudam estado. Catálogo dos crons (espelha `WorkerSettings.cron_jobs`):

| Cron | Cadência | Função | O que faz |
|---|---|---|---|
| `timeout_longo` | 5 min | `aplicar_timeout_longo` | 24h sem msg DO CLIENTE em pré-confirmação → `Perdido`/`sumiu` |
| `timeout_interno` | 1 min | `aplicar_timeout_interno` | interno com `aviso_saida` sem foto há 45min → `Perdido`/`sumiu` |
| `confirmar_em_execucao` | 1 min | `confirmar_em_execucao` | externo `Confirmado`→`Em_execucao` quando `bloqueio.inicio <= now` |
| `reengajar_silenciosos` | 5 min | `reengajar_silenciosos` | cliente sumiu após cotação há ~`reengajamento_delay_min` (Triagem/Qualificado, no horário, `reengajado_em IS NULL`) → 1 toque canned ao cliente + marca `reengajado_em`. **Só se `settings.reengajamento_ativo`** (`§4.5`, `01 §6.12`) |
| `limpar_midias` | diário 03:00 | `limpar_midias_vencidas` | GC de objetos MinIO 90d em estados terminais (política de mídia: `06`) |

### 4.1 `aplicar_timeout_longo` (24h)

`mvp/04 §5.1`. Conta da **última msg do cliente** (não de `conversas.ultima_mensagem_em`, que o trigger atualiza em QUALQUER direção — uma resposta da IA reabriria o relógio e o cliente sumido nunca expiraria). CTE única atômica: marca `Perdido`, cancela o bloqueio vinculado se ∉ {`em_atendimento`,`concluido`}, e emite **dois** eventos.

```python
async def aplicar_timeout_longo(conn) -> int:
    async with conn.transaction():
        result = await conn.execute("""
          WITH alvo AS (
            SELECT a.id, a.bloqueio_id, a.estado AS estado_anterior
              FROM barravips.atendimentos a
              LEFT JOIN LATERAL (
                SELECT max(created_at) AS ultima_cliente FROM barravips.mensagens m
                 WHERE m.atendimento_id = a.id AND m.direcao = 'cliente'
              ) msg ON true
             WHERE a.estado IN ('Novo','Triagem','Qualificado','Aguardando_confirmacao')
               AND a.ia_pausada = false
               AND COALESCE(msg.ultima_cliente, a.created_at) < now() - interval '24 hours'
             FOR UPDATE SKIP LOCKED
          ),
          upd AS (
            UPDATE barravips.atendimentos a
               SET estado='Perdido', motivo_perda='sumiu', fonte_decisao_ultima_transicao='auto_timeout'
              FROM alvo WHERE a.id = alvo.id
            RETURNING a.id, alvo.estado_anterior
          ),
          cancel_bloqueio AS (
            UPDATE barravips.bloqueios b SET estado='cancelado'
              FROM alvo WHERE b.id = alvo.bloqueio_id
                AND b.estado NOT IN ('em_atendimento','concluido')
            RETURNING b.id
          ),
          evt_transicao AS (
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            SELECT id, 'transicao_estado', 'cron', 'sistema',
                   jsonb_build_object('de', estado_anterior, 'para', 'Perdido', 'fonte', 'auto_timeout')
              FROM upd
            RETURNING id
          )
          INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
          SELECT id, 'perdido_registrado', 'cron', 'sistema', '{"fonte":"auto_timeout"}'::jsonb
            FROM upd
          RETURNING atendimento_id
        """)
        rows = await result.fetchall()
    TIMEOUTS.labels("longo").inc(len(rows))
    return len(rows)
```

> **Dois eventos por transição (2026-05-23):** além de `perdido_registrado` (que alimenta o dashboard de perdas), emite-se `transicao_estado {de, para:'Perdido'}` — alinhando com os outros caminhos de transição (kanban em `atendimentos/routes.py`, comando de grupo em `escaladas/service.py:_registrar_perdido`, e a própria tool `registrar_extracao`). Como timeout `sumiu` é a perda dominante, deixá-lo fora do log de transições seria buraco de auditoria. O `transicao_estado` vai num CTE lateral (`evt_transicao`) — o `RETURNING` final permanece só com `perdido_registrado`, então `len(rows)` **não** dobra. Hoje `transicao_estado` é write-only (sem consumidor de leitura), mas a consistência da trilha justifica o custo de 1 row.

### 4.2 `aplicar_timeout_interno` (45min)

`mvp/04 §5.2`. Mesma forma; alvo é interno em `Aguardando_confirmacao` com `aviso_saida_em` setado, sem `foto_portaria_em`, há mais de **45 minutos do aviso de saída** (`aviso_saida_em` — não do horário combinado/desejado). `fonte='auto_timeout_interno'`; emite os mesmos dois eventos. Métrica `TIMEOUTS.labels("interno")`.

### 4.3 `confirmar_em_execucao`

Transição determinística do fluxo **externo** (documentada na tabela de estados de `02 §`): `Confirmado`→`Em_execucao` quando o `bloqueio.inicio` chega, e o bloqueio vira `em_atendimento`. CTE única com `FOR UPDATE OF a SKIP LOCKED`. Métrica `TIMEOUTS.labels("em_execucao")`.

### 4.4 `limpar_midias_vencidas`

GC idempotente de objetos MinIO de atendimentos em estado terminal há 90d. A **política** de retenção de mídia é dona do `06`; aqui é só o cron que a executa.

### 4.5 `reengajar_silenciosos` (reengajamento proativo — atrás de flag)

**Decisão grilling 2026-05-23** (`01 §6.12`, `CONTEXT.md` "Reengajamento"). Ao contrário dos timeouts, este cron **envia mensagem ao cliente**: um toque proativo único quando o cliente recebeu a cotação e sumiu. Roda só com `settings.reengajamento_ativo=true` (default off no início do piloto).

Alvo (CTE atômica, `FOR UPDATE SKIP LOCKED`): atendimentos em `Triagem`/`Qualificado`, `ia_pausada=false`, `intencao IN ('cotacao','agendamento')` (proxy de "cotação apresentada"), `reengajado_em IS NULL`, última msg **do cliente** entre `reengajamento_delay_min` e 24h atrás, e hora local **dentro de `[operacao_hora_inicio, operacao_hora_fim)`**. O `UPDATE ... SET reengajado_em=now()` no mesmo CTE garante **1 toque por atendimento** (idempotente entre execuções concorrentes).

Para cada alvo, enfileira o envio ao cliente **reusando `enviar_turno`** (`05 §1`) com um chunk **canned** sorteado de um pool de reaberturas em persona (constante em `agente/`, mesma técnica do pool de disclosure `10 §3.1`), `midias=[]`, `critico=false`:

```python
# pool em agente/ (constante) — reabre com calor, SEM desconto (o reativo vem depois, 03 §3.1)
REENGAJAMENTO_CANNED = [
    "amor, vamos se ver hoje? to com a agenda boa hj",
    "oi sumido, ainda quer marcar? consigo um horario gostoso pra gente",
    "e ai amor, vamos marcar? to pensando em vc",
]
# no cron, por alvo:
turno_id = str(uuid5(NS_TURNO, f"reengajo:{a['id']}"))
await redis.set(f"turno_atual:{a['conversa_id']}", turno_id, ex=600)  # cancel-on-new-message protege
await redis.enqueue_job(
    "enviar_turno", conversa_id=str(a["conversa_id"]), turno_id=turno_id,
    chunks=[random.choice(REENGAJAMENTO_CANNED)], midias=[],
    msg_ids_cliente=[], chars_inbound=0,  # toque proativo: nada a marcar como lido → passo 0 pulado
    critico=False,
    _job_id=f"reengajo:{a['id']}",
)
```

Se o cliente responde antes do envio, o turno real sobrescreve `turno_atual` e o toque é cancelado (cancel-on-new-message, `05 §3.1`) — guarda natural contra reengajar quem voltou a falar. Não reseta o relógio de 24h (conta da última msg do **cliente**): sem resposta após o toque, o `timeout_longo` (§4.1) ainda encerra como `Perdido/sumiu`. Se o cliente responde e trava no preço, entra o **Desconto de fechamento** reativo (`03 §3.1`). Métrica `REENGAJAMENTO.labels("enviado")`.

---

**Os timeouts não enviam mensagem ao cliente** (`mvp/04 §5.1`/`§5.2`); a exceção é o `reengajar_silenciosos` (§4.5), que não é timeout. `SKIP LOCKED` evita conflito com workers paralelos varrendo a mesma janela. Os timeouts usam **compare-and-set** (guarda no `WHERE`), não o `lock:conv` — atômicos e instantâneos (`01 §6.10`).

> **TODO pós-piloto:** trocar varredura periódica por `pg_notify` em `INSERT`/`UPDATE` que setam `aviso_saida_em`/timestamps relevantes; worker assina o canal e processa sob demanda. Vale só se métricas mostrarem cron perdendo casos perto do limite (improvável no P0).

## 5. Pix nunca trava o fluxo (já implementado)

Conforme `01 §6.1` (grilling 2026-05-22): **nenhuma decisão de Pix pausa o fluxo esperando Fernando.** Tanto `validado` quanto `em_revisao` (duvidoso) levam o atendimento a `Confirmado` com `ia_pausada=true` (motivo `modelo_em_atendimento`) — a mesma transição do handoff implícito de saída.

**Já implementado** em `dominio/escaladas/service.py:_atualizar_pix` (não é mudança pendente). O `UPDATE` seta `pix_status ∈ {validado, em_revisao}`, `estado='Confirmado'`, `ia_pausada=true`, `ia_pausada_motivo='modelo_em_atendimento'` em ambos os casos. A duvidez (`em_revisao`) é informativa: sinaliza no card à modelo (que decide pedir o Uber) e entra numa fila assíncrona de revisão de Fernando no painel (`comprovantes_pix.decisao_final`).

> **Não há mais branch bloqueante** que preservava `ia_pausada` por `pix_em_revisao` esperando Fernando. O pipeline de validação (`workers/pix.py:validar_pix`, vision) é dono do `06`.

## 6. Métricas

Já existem em `core/metrics.py` (ver `08`) — o coordenador **reusa** estes símbolos (o código da §3 usa o nome curto `TURNO_*` como abreviação dos `AGENTE_TURNO_*`):

```python
AGENTE_TURNO_DURACAO   = Histogram("agente_turno_duracao_seconds", ..., ["modelo"])  # .labels(modelo_id).observe(...)
AGENTE_TURNO_RESULTADO = Counter("agente_turno_resultado_total", ..., ["resultado"])
                         # ok | escalado | exaustao | ia_pausada_skip | transcricao_timeout | ok_sem_resposta
AGENTE_TURNO_TOKENS    = Counter("agente_turno_tokens_total", ..., ["tipo"])  # input|output|cache_read|cache_write
TIMEOUTS               = Counter("barra_timeouts_total", ..., ["tipo"])       # longo|interno|em_execucao
```

**A adicionar** quando `coordenador.py` for construído:

```python
LOCK_OCUPADO = Counter("agente_lock_ocupado_total", "lock:conv estava ocupado (re-defer)")
```

> Os nomes `TURNO_DURACAO/TURNO_RESULTADO/TURNO_TOKENS/TIMEOUT_AFETADOS/ESCALADA` de versões anteriores deste doc **não existem** em `core/metrics.py`. Canônicos: `AGENTE_TURNO_DURACAO` (label `modelo`), `AGENTE_TURNO_RESULTADO` (label `resultado`), `AGENTE_TURNO_TOKENS` (label `tipo`), `TIMEOUTS` (label `tipo`). Escaladas são contadas via eventos/handoff (`08`), não por um counter `ESCALADA` dedicado.
