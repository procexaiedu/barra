"""Coordenador de turno — worker ARQ `processar_turno` (07 §3).

O webhook so enfileira; quem roda o turno e este worker: adquire `lock:conv`, resolve o
atendimento de forma deterministica, cobre mensagens orfas, invoca o grafo (montado do zero a
cada turno — sem checkpointer no P0) e despacha a resposta para a humanizacao (`enviar_turno`).

Drain bounded (01 §4.3): enquanto chegarem mensagens com o lock retido, re-roda sob o MESMO
lock ate `MAX_DRAIN`; ao estourar, re-enfileira a si mesmo (libera o lock). `turno_id` e
deterministico por (job, iteracao) — o retry do ARQ reusa as dedupe keys de envio sem duplicar
a resposta (01 §6.7).
"""

import asyncio
import logging
from datetime import timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid5

from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.agente.contexto import ContextAgente
from barra.core.metrics import (
    AGENTE_TURNO_DURACAO,
    AGENTE_TURNO_RESULTADO,
    LOCK_OCUPADO,
)
from barra.core.redis import LockBusy, adquirir_lock

logger = logging.getLogger(__name__)

# Namespace fixo para turno_id deterministico (01 §6.7). NUNCA uuid7() runtime — o retry do ARQ
# regeneraria turno_id novo, furaria as dedupe de envio e duplicaria a resposta.
NS_TURNO = UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")

ESTADOS_TERMINAIS = {"Fechado", "Perdido"}
MAX_DRAIN = 5  # teto de iteracoes de drain sob o MESMO lock; ao estourar, re-enfileira
RECURSION_LIMIT = 18  # ~6-7 round-trips llm<->tools (5 tools no P0). DORMENTE ate o loop de M1


async def processar_turno(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    aguardar_transcricao: bool = False,
) -> None:
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    graph = ctx["graph"]
    settings = ctx["settings"]

    conv_uuid = UUID(conversa_id)
    modelo_anthropic = settings.anthropic_modelo_principal
    tipo_turno = "audio" if aguardar_transcricao else "texto"

    # O lock contende SO com rotear_imagem (06 §2.1). Ocupado -> re-defere curto; o pending ja
    # foi setado por enfileirar_turno, entao ao re-disparar o turno le a janela inteira.
    try:
        async with adquirir_lock(
            redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15
        ):
            for loop_idx in range(MAX_DRAIN):  # DRAIN LOOP BOUNDED (01 §4.3)
                turno_id = str(uuid5(NS_TURNO, f"{ctx['job_id']}:{loop_idx}"))
                await redis.delete(f"pending:conv:{conversa_id}")  # limpa ANTES de ler a janela

                # 1. resolver atendimento e cobrir orfas.
                # NB: o §3 emitia tambem registrar_evento_turno_iniciado aqui — omitido: nao ha
                # valor 'turno_iniciado' em tipo_evento_enum (0001) e nao consta dos entregaveis.
                async with pool.connection() as conn, conn.transaction():
                    atendimento = await resolver_atendimento(conn, conv_uuid)
                    await atualizar_orfaos(conn, conv_uuid, atendimento["id"])

                # 2. gates (ia_pausada OU estado terminal -> encerra)
                if atendimento["ia_pausada"] or atendimento["estado"] in ESTADOS_TERMINAIS:
                    logger.info(
                        "turno_skipped conversa_id=%s estado=%s",
                        conversa_id,
                        atendimento["estado"],
                    )
                    AGENTE_TURNO_RESULTADO.labels("ia_pausada_skip").inc()
                    break

                if aguardar_transcricao:
                    # TODO(M5): BLPOP do canal de transcricao (06 §1.4) antes de montar a janela;
                    # a porta de audio nasce no M5 (aguardar_transcricoes). Por ora segue direto.
                    logger.info("aguardar_transcricao ignorado no M3b (M5) conversa_id=%s", conversa_id)

                # 3. marca o turno atual — cancel-on-new-message (05 §3.1): o enviar_turno do turno
                #    anterior compara turno_atual e aborta os chunks pendentes ao ser superado.
                await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)

                # 4. config (thread_id + recursion_limit, nativos do LangGraph) + context (deps e
                #    ids de escopo via Runtime Context API — 04 §1.1). prepare_context monta o
                #    prompt do zero dentro do grafo (03 §7), entrada vai vazia.
                config: dict[str, Any] = {
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
                entrada: dict[str, Any] = {"messages": []}

                # 5. invoca grafo (teto de tempo por iteracao; o job_timeout do ARQ e generoso)
                inicio = perf_counter()
                try:
                    resultado = await asyncio.wait_for(
                        graph.ainvoke(entrada, config=config, context=context),
                        timeout=60.0,
                    )
                except TimeoutError:
                    logger.error("graph_timeout turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="timeout_grafo"
                    )
                    AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    break
                except GraphRecursionError:
                    # captura por CLASSE (langgraph.errors), nao por string (09 §4.7). DORMENTE ate
                    # o loop llm<->tools de M1 ser exercido.
                    logger.error("graph_recursion turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="exaustao_iteracoes"
                    )
                    AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    break
                except Exception:
                    logger.exception("graph_erro turno_id=%s", turno_id)
                    raise
                finally:
                    AGENTE_TURNO_DURACAO.labels(modelo_anthropic, tipo_turno).observe(
                        perf_counter() - inicio
                    )

                # 6. cinto-suspensorio (01 §6.10): se um pipeline sem lock (Pix/foto) pausou a IA
                #    OU o estado virou terminal durante o turno -> descarta o texto.
                async with pool.connection() as conn:
                    res = await conn.execute(
                        "SELECT ia_pausada, estado FROM barravips.atendimentos WHERE id = %s",
                        (atendimento["id"],),
                    )
                    pos = await res.fetchone()
                assert pos is not None
                if pos["ia_pausada"] or pos["estado"] in ESTADOS_TERMINAIS:
                    logger.info("turno_descartado atendimento_id=%s", atendimento["id"])
                    AGENTE_TURNO_RESULTADO.labels("escalado").inc()
                else:
                    # 7. extrai resposta + msgs do cliente do turno (read receipt, 05 §4.2).
                    ai_final = next(
                        (m for m in reversed(resultado["messages"]) if isinstance(m, AIMessage)),
                        None,
                    )
                    texto = _extrair_texto(ai_final) if ai_final is not None else ""
                    # midias e critico dependem de barravips.tool_calls (M3a) + write tools
                    # (M3d/M3e): no M3b o grafo so produz texto, entao ambos sao vazios.
                    midias: list[dict[str, Any]] = []  # TODO(M4d): coletar enviar_midia de tool_calls
                    critico = False  # TODO(M3d/M3e): turno critico via tool_calls (pedir_pix/extracao)

                    async with pool.connection() as conn:
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
                            (conv_uuid, conv_uuid),
                        )
                        inbound = await res.fetchall()
                    msg_ids_cliente: list[str] = [r["evolution_message_id"] for r in inbound]
                    chars_inbound = sum(len(r["conteudo"] or "") for r in inbound)

                    chunks = _chunk_texto(texto)
                    if not chunks and not midias:
                        logger.warning("turno_sem_resposta turno_id=%s", turno_id)
                        AGENTE_TURNO_RESULTADO.labels("ok_sem_resposta").inc()
                    else:
                        # NB: metricas de tokens NAO sao emitidas aqui — o no llm ja emite
                        # AGENTE_TURNO_TOKENS (M2-T2, via ephemeral_5m+1h). Reemitir duplicaria a
                        # contagem e reintroduziria o bug do cache_creation=0 (auditoria 24-05).
                        await despachar_humanizacao(
                            ctx,
                            conversa_id,
                            turno_id,
                            chunks,
                            midias,
                            msg_ids_cliente,
                            chars_inbound,
                            critico,
                        )
                        AGENTE_TURNO_RESULTADO.labels("ok").inc()

                # 8. drena: chegou msg com o lock retido? re-roda sob o MESMO lock; senao sai.
                if not await redis.get(f"pending:conv:{conversa_id}"):
                    break
            else:
                # teto de drain estourado com pending ainda cheio -> re-enfileira (libera o lock).
                # Evita prender um worker slot num cliente tagarela.
                if await redis.get(f"pending:conv:{conversa_id}"):
                    await redis.enqueue_job(
                        "processar_turno",
                        conversa_id=conversa_id,
                        aguardar_transcricao=False,
                        _job_id=f"turno:{conversa_id}",
                        _defer_by=timedelta(seconds=2),
                    )
    except LockBusy:
        # contenda com rotear_imagem (06 §2.1) — re-defere curto via ctx["redis"] (ArqRedis).
        await redis.enqueue_job(
            "processar_turno",
            conversa_id=conversa_id,
            aguardar_transcricao=aguardar_transcricao,
            _job_id=f"turno:{conversa_id}",
            _defer_by=timedelta(seconds=2),
        )
        LOCK_OCUPADO.inc()


def _extrair_texto(msg: AIMessage) -> str:
    """Texto plano da AIMessage final. content pode ser str ou lista de blocos (1.x)."""
    if isinstance(msg.content, str):
        return msg.content
    partes = [
        bloco.get("text", "")
        for bloco in msg.content
        if isinstance(bloco, dict) and bloco.get("type") == "text"
    ]
    return "".join(partes)


def _chunk_texto(texto: str) -> list[str]:
    # TODO(M4a): trocar por workers._chunking.chunk_texto (split \n\n, cap 600 soft, cap 6 bolhas).
    return [bloco.strip() for bloco in texto.split("\n\n") if bloco.strip()]


async def resolver_atendimento(
    conn: AsyncConnection[dict[str, Any]], conversa_id: UUID
) -> dict[str, Any]:
    """Busca o atendimento aberto da conversa; cria em Novo se nao houver (07 §3.2)."""
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
    novo = await res.fetchone()
    assert novo is not None  # INSERT ... RETURNING sempre devolve a linha criada
    return novo


async def atualizar_orfaos(
    conn: AsyncConnection[Any], conversa_id: UUID, atendimento_id: UUID
) -> None:
    """Vincula mensagens orfas (atendimento_id=NULL) ao atendimento corrente (07 §3.2)."""
    await conn.execute(
        """
        UPDATE barravips.mensagens
           SET atendimento_id = %s
         WHERE conversa_id = %s AND atendimento_id IS NULL
        """,
        (atendimento_id, conversa_id),
    )


async def escalar_por_exaustao(
    pool: AsyncConnectionPool[Any],
    atendimento_id: UUID,
    turno_id: str,
    motivo: str = "exaustao_iteracoes",
) -> None:
    """Abre handoff para Fernando sem mensagem ao cliente (07 §3.3).

    A `abrir_handoff` shipada NAO aceita `motivo=` (09 §4.3): mapeia-se o motivo de exaustao para
    `tipo=TipoEscalada.outro` + `responsavel="Fernando"` e o motivo literal vai em `observacao`.
    TODO(M3f): quando escaladas/service.py expuser o mapping motivo->(tipo,responsavel), adotar
    aqui em vez do hardcode (motivos timeout_grafo/exaustao_iteracoes/modelo_recusou -> Fernando).
    """
    from barra.dominio.escaladas.modelos import TipoEscalada
    from barra.dominio.escaladas.service import abrir_handoff

    async with pool.connection() as conn:
        await abrir_handoff(
            conn,
            atendimento_id=atendimento_id,
            responsavel="Fernando",
            tipo=TipoEscalada.outro,
            resumo_operacional=(
                f"Agente nao encerrou o turno: estourou recursion_limit "
                f"({RECURSION_LIMIT} super-steps ~= {RECURSION_LIMIT // 2} round-trips) ou "
                f"excedeu 60s. turno_id={turno_id}. Verificar trace LangSmith."
            ),
            acao_esperada="Revisar trace, decidir se devolve para IA ou assume manualmente.",
            origem="agente",
            autor="sistema",
            observacao=motivo,
        )


async def despachar_humanizacao(
    ctx: dict[str, Any],
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict[str, Any]],
    msg_ids_cliente: list[str],
    chars_inbound: int,
    critico: bool,
) -> None:
    """Um unico job `enviar_turno` por turno (05 §1): percorre chunks e midias em ordem (07 §3.4).

    O job `enviar_turno` nasce no M4c; aqui so o despacho pelo NOME, com dedupe nativo via _job_id.
    """
    arq = ctx["redis"]  # em ARQ, ctx["redis"] e a ArqRedis e expoe enqueue_job
    await arq.enqueue_job(
        "enviar_turno",
        conversa_id=conversa_id,
        turno_id=turno_id,
        chunks=chunks,
        midias=midias,
        msg_ids_cliente=msg_ids_cliente,
        chars_inbound=chars_inbound,
        critico=critico,
        _job_id=f"turno_envio:{turno_id}",
    )
