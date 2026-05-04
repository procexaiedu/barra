# 07 — Coordenador de Turno e Cron de Timeouts

> Detalhe completo do worker `processar_turno`, lock Redis, debounce, resolução determinística, exaustão e cron de timeouts.

## 1. Por que ARQ e não inline no webhook

Webhook tem timeout do Evolution (~15s). Turno de IA com 5+ tool calls + Sonnet 4.6 pode passar de 8s (especialmente com adaptive thinking ativo). Inline arrisca:
- Webhook responder 504 → Evolution retentar → segunda mensagem persistida.
- Bloqueio do event loop FastAPI.

Worker ARQ desacopla: webhook responde 200 imediatamente após persistir + enfileirar; turno roda em processo separado, com timeout próprio (60s), retries idempotentes.

## 2. Estrutura do worker

```python
# api/src/barra/workers/settings.py
from arq.connections import RedisSettings
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from barra.agente.graph import build_graph
from barra.core.evolution import EvolutionClient
from barra.core.redis import criar_redis
from barra.core.storage import criar_minio
from barra.settings import get_settings

from .coordenador import processar_turno
from .envio import enviar_chunk, enviar_midia, enviar_card_grupo
from .media import transcrever_audio
from .pix import validar_pix
from .timeouts import varrer_timeouts


class WorkerSettings:
    redis_settings = RedisSettings(...)
    functions = [
        processar_turno, enviar_chunk, enviar_midia, enviar_card_grupo,
        transcrever_audio, validar_pix,
    ]
    cron_jobs = [varrer_timeouts, limpar_checkpoints_antigos]  # see §4 e 02 §3.2
    max_jobs = 20
    job_timeout = 90  # segundos

    @classmethod
    async def on_startup(cls, ctx):
        from barra.core.llm import criar_anthropic_client

        settings = get_settings()
        ctx["settings"] = settings
        ctx["redis"] = await criar_redis(settings.redis_url)
        ctx["minio"] = criar_minio(settings)
        ctx["evolution"] = EvolutionClient(settings.evolution_base_url, settings.evolution_api_key)
        # Anthropic client raw (usado por workers/pix.py em vision)
        ctx["anthropic_client"] = criar_anthropic_client(settings)
        pool = AsyncConnectionPool(
            settings.database_url,
            min_size=4, max_size=20,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        await pool.open()
        ctx["db_pool"] = pool
        cp = AsyncPostgresSaver(pool)
        await cp.setup()
        ctx["graph"] = build_graph(cp, settings)

    @classmethod
    async def on_shutdown(cls, ctx):
        await ctx["db_pool"].close()
        await ctx["redis"].close()
        await ctx["anthropic_client"].close()
```

## 3. `processar_turno` — implementação completa

```python
# api/src/barra/workers/coordenador.py
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID
from uuid_extensions import uuid7  # uuidv7

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from barra.agente.persona import carregar_persona, render_persona_completa
from barra.workers._chunking import chunk_texto


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
    turno_id = str(uuid7())

    async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
        # 1. resolver atendimento e cobrir órfãs
        async with pool.connection() as conn, conn.transaction():
            atendimento = await resolver_atendimento(conn, UUID(conversa_id))
            await atualizar_orfaos(conn, UUID(conversa_id), atendimento["id"])
            await registrar_evento_turno_iniciado(conn, atendimento["id"], turno_id)

        # 2. gates
        if atendimento["ia_pausada"]:
            logger.info("turno_skipped_ia_pausada", conversa_id=conversa_id)
            TURNO_RESULTADO.labels("ia_pausada_skip").inc()
            return

        if aguardar_transcricao:
            ok = await aguardar_transcricoes(redis, atendimento["id"], timeout=8)
            if not ok:
                logger.warning("transcricao_timeout", atendimento_id=atendimento["id"])
                TURNO_RESULTADO.labels("transcricao_timeout").inc()
                # segue mesmo assim com placeholder

        # 3. cancela jobs pendentes do turno anterior (se houver)
        await cancelar_turno_anterior(redis, UUID(conversa_id))
        await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)

        # 4. monta contexto
        async with pool.connection() as conn:
            persona_ctx = await carregar_persona(conn, atendimento["modelo_id"])
            mensagens = await carregar_mensagens(conn, UUID(conversa_id), limite=20)
            agenda = await carregar_agenda_proximas_48h(conn, atendimento["modelo_id"])
            cliente = await carregar_cliente(conn, atendimento["cliente_id"])
            conversa = await carregar_conversa(conn, UUID(conversa_id))

        system_msgs = render_persona_completa(persona_ctx)  # 4 SystemMessages com cache_ttl
        contexto_din = render_contexto_dinamico(atendimento, cliente, conversa, agenda, turno_id)
        system_msgs.append(SystemMessage(content=contexto_din, additional_kwargs={"cache_ttl": "5m"}))

        historico_lc = traduzir_mensagens(mensagens)

        config = {
            "configurable": {
                "thread_id": conversa_id,
                "atendimento_id": str(atendimento["id"]),
                "modelo_id": str(atendimento["modelo_id"]),
                "cliente_id": str(atendimento["cliente_id"]),
                "conversa_id": conversa_id,
                "turno_id": turno_id,
                "db_pool": pool,
                "redis": redis,
                "settings": settings,
            },
            "recursion_limit": 25,
        }
        entrada = {"messages": system_msgs + historico_lc}

        # 5. invoca grafo
        inicio = asyncio.get_event_loop().time()
        try:
            resultado = await asyncio.wait_for(
                graph.ainvoke(entrada, config=config),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.error("graph_timeout", turno_id=turno_id)
            await escalar_por_exaustao(pool, atendimento["id"], turno_id, motivo="timeout_grafo")
            TURNO_RESULTADO.labels("exaustao").inc()
            return
        except Exception as e:
            if "recursion" in str(e).lower():
                await escalar_por_exaustao(pool, atendimento["id"], turno_id, motivo="exaustao_iteracoes")
                TURNO_RESULTADO.labels("exaustao").inc()
                return
            logger.exception("graph_erro", turno_id=turno_id)
            raise
        finally:
            duracao = asyncio.get_event_loop().time() - inicio
            TURNO_DURACAO.observe(duracao)

        # 6. checa escalada (cinto-suspensório)
        async with pool.connection() as conn:
            res = await conn.execute(
                "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
                (atendimento["id"],),
            )
            pos = await res.fetchone()
        if pos["ia_pausada"]:
            logger.info("turno_escalado", atendimento_id=atendimento["id"])
            TURNO_RESULTADO.labels("escalado").inc()
            # registra tokens e volta sem despachar
            return

        # 7. extrai resposta + mídias
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

        chunks = chunk_texto(texto)
        if not chunks and not midias:
            logger.warning("turno_sem_resposta", turno_id=turno_id)
            TURNO_RESULTADO.labels("ok_sem_resposta").inc()
            return

        # 8. registra chunks pendentes e despacha
        await registrar_chunks_pendentes(redis, UUID(turno_id), chunks, midias)
        for idx, ch in enumerate(chunks):
            await ctx["redis"].xadd("arq:queue:envio", {})  # via arq enqueue real:
        await despachar_humanizacao(ctx, conversa_id, turno_id, chunks, midias)

        # 9. métricas de tokens (se disponíveis na response_metadata do AIMessage)
        usage = ai_final.response_metadata.get("usage", {})
        if usage:
            TURNO_TOKENS.labels("input").inc(usage.get("prompt_tokens", 0))
            TURNO_TOKENS.labels("output").inc(usage.get("completion_tokens", 0))
            TURNO_TOKENS.labels("cache_read").inc(usage.get("cache_read_input_tokens", 0))
            TURNO_TOKENS.labels("cache_write").inc(usage.get("cache_creation_input_tokens", 0))

        TURNO_RESULTADO.labels("ok").inc()
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
                "Agente não conseguiu encerrar turno em 10 iterações ou excedeu 60s. "
                f"turno_id={turno_id}. Verificar trace LangSmith."
            ),
            acao_esperada="Revisar trace, decidir se devolve para IA ou assume manualmente.",
            origem="agente",
            autor="sistema",
        )
```

### 3.4 Despacho da humanização

```python
async def despachar_humanizacao(
    ctx,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict],
) -> None:
    arq = ctx["arq_pool"]  # arq.connections.ArqRedis
    for idx, conteudo in enumerate(chunks):
        await arq.enqueue_job(
            "enviar_chunk",
            conversa_id=conversa_id,
            turno_id=turno_id,
            chunk_idx=idx,
            conteudo=conteudo,
            _job_id=f"chunk:{turno_id}:{idx}",
        )
    for idx, m in enumerate(midias):
        await arq.enqueue_job(
            "enviar_midia",
            conversa_id=conversa_id,
            turno_id=turno_id,
            midia_idx=idx,
            midia_id=m["midia_id"],
            legenda=m["legenda"] or "",
            _job_id=f"midia:{turno_id}:{idx}",
        )
```

## 4. Cron de timeouts

```python
# api/src/barra/workers/timeouts.py
from arq import cron
from datetime import timedelta

@cron(minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})
async def varrer_timeouts(ctx) -> None:
    pool = ctx["db_pool"]
    redis = ctx["redis"]

    async with pool.connection() as conn:
        await _timeout_longo_24h(conn)
        await _timeout_interno_30min(conn, redis)


async def _timeout_longo_24h(conn) -> None:
    """mvp/04 §5.1: 24h sem mensagem em pré-confirmação → Perdido motivo=sumiu."""
    res = await conn.execute(
        """
        WITH alvo AS (
          SELECT a.id, a.estado
            FROM barravips.atendimentos a
            JOIN barravips.conversas c ON c.id = a.conversa_id
           WHERE a.estado IN ('Novo', 'Triagem', 'Qualificado', 'Aguardando_confirmacao')
             AND a.ia_pausada = false
             AND c.ultima_mensagem_em < now() - interval '24 hours'
           FOR UPDATE OF a SKIP LOCKED
        )
        UPDATE barravips.atendimentos a
           SET estado = 'Perdido',
               motivo_perda = 'sumiu',
               fonte_decisao_ultima_transicao = 'auto_timeout'
          FROM alvo
         WHERE a.id = alvo.id
        RETURNING a.id, a.bloqueio_id, alvo.estado AS estado_anterior
        """,
    )
    afetados = await res.fetchall()
    for a in afetados:
        # cancela bloqueio se aplicável
        if a["bloqueio_id"]:
            await conn.execute(
                """
                UPDATE barravips.bloqueios
                   SET estado = 'cancelado'
                 WHERE id = %s AND estado NOT IN ('em_atendimento', 'concluido')
                """,
                (a["bloqueio_id"],),
            )
        # eventos
        await conn.execute(
            """
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            VALUES (%s, 'transicao_estado', 'cron', 'sistema', %s),
                   (%s, 'perdido_registrado', 'cron', 'sistema', %s)
            """,
            (a["id"], json.dumps({"de": a["estado_anterior"], "para": "Perdido"}),
             a["id"], json.dumps({"motivo": "sumiu", "auto_timeout": True})),
        )
    if afetados:
        TIMEOUT_AFETADOS.labels("longo_24h").inc(len(afetados))


async def _timeout_interno_30min(conn, redis) -> None:
    """mvp/04 §5.2: interno com aviso_saida sem foto há 30min → Perdido motivo=sumiu."""
    res = await conn.execute(
        """
        WITH alvo AS (
          SELECT a.id, a.bloqueio_id, a.estado
            FROM barravips.atendimentos a
           WHERE a.estado = 'Aguardando_confirmacao'
             AND a.tipo_atendimento = 'interno'
             AND a.aviso_saida_em IS NOT NULL
             AND a.foto_portaria_em IS NULL
             AND a.data_desejada IS NOT NULL
             AND a.horario_desejado IS NOT NULL
             AND (a.data_desejada::timestamp + a.horario_desejado::time) < now() - interval '30 minutes'
           FOR UPDATE OF a SKIP LOCKED
        )
        UPDATE barravips.atendimentos a
           SET estado = 'Perdido',
               motivo_perda = 'sumiu',
               fonte_decisao_ultima_transicao = 'auto_timeout_interno'
          FROM alvo
         WHERE a.id = alvo.id
        RETURNING a.id, alvo.bloqueio_id, alvo.estado AS estado_anterior
        """,
    )
    afetados = await res.fetchall()
    for a in afetados:
        if a["bloqueio_id"]:
            await conn.execute(
                """
                UPDATE barravips.bloqueios SET estado = 'cancelado'
                 WHERE id = %s AND estado NOT IN ('em_atendimento', 'concluido')
                """,
                (a["bloqueio_id"],),
            )
        await conn.execute(
            """
            INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
            VALUES (%s, 'transicao_estado', 'cron', 'sistema', %s),
                   (%s, 'perdido_registrado', 'cron', 'sistema', %s)
            """,
            (a["id"], json.dumps({"de": a["estado_anterior"], "para": "Perdido"}),
             a["id"], json.dumps({"motivo": "sumiu", "auto_timeout_interno": True})),
        )
    if afetados:
        TIMEOUT_AFETADOS.labels("interno_30min").inc(len(afetados))
```

**Não envia mensagem ao cliente** (`mvp/04 §5.1` e `§5.2`).

`SKIP LOCKED` evita conflito com workers paralelos varrendo a mesma janela.

> **TODO pós-piloto:** trocar varredura periódica por `pg_notify` disparado em `INSERT` ou `UPDATE` que setam `aviso_saida_em`/timestamps relevantes. Worker assina canal e processa sob demanda — elimina varredura. Vale apenas se métricas mostrarem que cron 5min está perdendo casos próximos do limite (improvável no P0).

## 5. Override do Pix recusado

Conforme decisão QA (`01 §6.1`): `atualizar_pix(invalido)` mantém `ia_pausada=true`. Modificar `dominio/escaladas/service.py:_atualizar_pix`:

```python
# api/src/barra/dominio/escaladas/service.py — diff conceitual
if decisao == "invalido":
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET pix_status = 'invalido',
               -- override (docs/agente/01 §6.1): mantém ia_pausada=true após recusa
               -- ia_pausada já está true desde Pix em revisão (motivo=pix_em_revisao)
               -- Fernando precisa ativamente devolver via painel ou comando 'IA assume'
               ia_pausada_motivo = 'pix_em_revisao',
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (_fonte(origem), atendimento["id"]),
    )
```

> **Mudança:** remover as linhas `ia_pausada = false` e `ia_pausada_motivo = NULL` do branch invalido. Adicionar comment apontando para `docs/agente/01 §6.1`.

## 6. Métricas exportadas

```python
# api/src/barra/core/metrics.py — adicionar
from prometheus_client import Counter, Histogram

TURNO_DURACAO = Histogram(
    "agente_turno_duracao_seconds",
    "Duração total do turno (lock até dispatch)",
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 60),
)
TURNO_RESULTADO = Counter("agente_turno_resultado_total", "Resultado do turno", ["resultado"])
TURNO_TOKENS = Counter("agente_turno_tokens_total", "Tokens consumidos por turno", ["tipo"])
TIMEOUT_AFETADOS = Counter("agente_timeout_afetados_total", "Atendimentos marcados por timeout", ["tipo"])
LOCK_OCUPADO = Counter("agente_lock_ocupado_total", "Lock de conversa estava ocupado")
```
