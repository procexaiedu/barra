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
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid5

import structlog
from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.errors import GraphRecursionError
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.agente._canned import escolher_canned_transcricao_falhou
from barra.agente.contexto import ContextAgente
from barra.agente.nos.output_guard import tem_marcador_ia
from barra.core.metrics import (
    AGENTE_ESCALADA,
    AGENTE_EVAL_PASS_RATE,
    AGENTE_TURNO_DURACAO,
    AGENTE_TURNO_RESULTADO,
    LOCK_OCUPADO,
)
from barra.core.redis import LockBusy, adquirir_lock
from barra.settings import get_settings
from barra.workers._chunking import chunk_texto

logger = logging.getLogger(__name__)

# Namespace fixo para turno_id deterministico (01 §6.7). NUNCA uuid7() runtime — o retry do ARQ
# regeneraria turno_id novo, furaria as dedupe de envio e duplicaria a resposta.
NS_TURNO = UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")

ESTADOS_TERMINAIS = {"Fechado", "Perdido"}
MAX_DRAIN = 5  # teto de iteracoes de drain sob o MESMO lock; ao estourar, re-enfileira
RECURSION_LIMIT = 18  # ~6-7 round-trips llm<->tools (5 tools no P0). DORMENTE ate o loop de M1
# Teto de turnos por conversa/dia (CUSTO-04): contador Redis (`turnos:conv:{id}:{YYYY-MM-DD}`,
# auto-expira em 24h) que, ao estourar, escala a Fernando em vez de deixar um cliente em loop
# queimar orcamento ate o timeout de 24h. Default conservador, bem acima de uma negociacao
# normal; tuning sem deploy nao foi pedido (constante local, no padrao de MAX_DRAIN).
TETO_TURNOS_DIA = 50


async def processar_turno(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    aguardar_transcricao: bool = False,
    request_id: str | None = None,
) -> None:
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    graph = ctx["graph"]
    settings = ctx["settings"]

    # OBS-07: bind do request-id da API nos logs JSON (OBS-03) deste turno. Cada job ARQ roda no
    # proprio contextvars.Context (worker cria task por job), entao o bind nao vaza entre turnos.
    if request_id is not None:
        structlog.contextvars.bind_contextvars(request_id=request_id)

    conv_uuid = UUID(conversa_id)
    modelo_anthropic = settings.anthropic_modelo_principal
    tipo_turno = "audio" if aguardar_transcricao else "texto"

    # O lock contende SO com rotear_imagem (06 §2.1). Ocupado -> re-defere curto; o pending ja
    # foi setado por enfileirar_turno, entao ao re-disparar o turno le a janela inteira.
    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            for loop_idx in range(MAX_DRAIN):  # DRAIN LOOP BOUNDED (01 §4.3)
                # `ctx['score']` (timestamp ms do enqueue) e estavel no retry do MESMO job
                # (preserva dedupe de envio) e UNICO entre turnos distintos (cada webhook
                # gera novo enqueue -> novo score -> novo turno_id). Sem ele, `_job_id`
                # estatico por conversa colidia turnos diferentes no mesmo turno_id.
                turno_id = str(uuid5(NS_TURNO, f"{ctx['job_id']}:{ctx['score']}:{loop_idx}"))
                # OBS-07/OBS-03: turno_id como campo dos logs JSON, junto do request_id.
                structlog.contextvars.bind_contextvars(turno_id=turno_id)
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

                # 2.5. teto de turnos/conversa/dia (CUSTO-04): contador Redis por conversa+dia que,
                #      ao estourar, escala a Fernando (custo) em vez de deixar um cliente em loop
                #      queimar orcamento ate o timeout de 24h. CHECAGEM aqui (read-only, ANTES do
                #      grafo: ao bater o teto nao processa o turno); o INCREMENTO so acontece apos
                #      o grafo responder (mais abaixo) — assim um turno que falhou e foi retentado
                #      pelo ARQ nao infla o contador nem escala falso. A data na chave faz o reset
                #      diario; o TTL de 24h e so faxina. O retry-after de 429/5xx ja e tratado pelo
                #      SDK (best-practices §196) + o ramo modelo_indisponivel; este teto e a parte.
                chave_teto = f"turnos:conv:{conversa_id}:{datetime.now(UTC):%Y-%m-%d}"
                ja_contados = int(await redis.get(chave_teto) or 0)
                if ja_contados >= TETO_TURNOS_DIA:
                    logger.warning(
                        "teto_turnos conversa_id=%s n=%s teto=%s",
                        conversa_id,
                        ja_contados,
                        TETO_TURNOS_DIA,
                    )
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="teto_turnos"
                    )
                    AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    break

                if aguardar_transcricao:
                    # BLPOP do canal `transcricao:{conversa_id}` (06 §1.4): sinaliza ok=true do
                    # worker (mensagens.conteudo ja preenchido) ou ok=false / timeout (resposta
                    # canned, sem invocar LLM).
                    ok = await aguardar_transcricoes(redis, conversa_id, orcamento_s=8)
                    if not ok:
                        logger.warning(
                            "transcricao_falhou conversa_id=%s turno_id=%s", conversa_id, turno_id
                        )
                        AGENTE_TURNO_RESULTADO.labels("transcricao_timeout").inc()
                        # Despacha canned via humanizacao (mantem read receipt / dedupe). Como
                        # nao houve LLM, midias e critico ficam vazios; o `enviar_turno` recebe
                        # so o chunk canned. msg_ids_cliente e chars_inbound zerados — o audio
                        # nao gera read receipt aqui (a humanizacao continua mandando reads na
                        # proxima mensagem do cliente).
                        canned = escolher_canned_transcricao_falhou()
                        await despachar_humanizacao(
                            ctx,
                            conversa_id,
                            turno_id,
                            chunks=[canned],
                            midias=[],
                            msg_ids_cliente=[],
                            chars_inbound=0,
                            critico=False,
                        )
                        # Encerra o turno atual; nao re-roda drain (canned ja respondeu).
                        break

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
                except (RateLimitError, APITimeoutError, APIStatusError):
                    # 5xx/timeout persistente da API do LLM (Anthropic) — falha de plataforma, nao
                    # bug do grafo. O no llm ja re-levanta esses erros (nos/llm.py); aqui escala
                    # como modelo_indisponivel (bucket infra) em vez de cair no `except Exception`
                    # generico abaixo, que jogaria para o retry do ARQ.
                    logger.error("api_indisponivel turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="modelo_indisponivel"
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

                # 5a. contabiliza o turno (CUSTO-04): so apos o grafo responder — turno que falhou
                #     (excecao -> break/retry) nao chega aqui, entao nao infla o teto. RMW (nao
                #     INCR) e seguro: todo o turno roda sob `lock:conv`, escritor unico por conversa.
                await redis.set(chave_teto, ja_contados + 1, ex=86400)

                # 5b. refusal do Sonnet (stop_reason=refusal chega em 200 OK, nao como excecao; o
                #     no llm ja logou stop_details.category). O sinal vem no response_metadata da
                #     AIMessage gerada no turno (canal `messages`). Escala defesa (modelo_recusou)
                #     e encerra SEM bolha crua ao cliente: abrir_handoff pausa a IA e Fernando
                #     assume — mesmo padrao dos demais ramos de exaustao.
                if any(
                    isinstance(m, AIMessage)
                    and m.usage_metadata is not None
                    and (m.response_metadata or {}).get("stop_reason") == "refusal"
                    for m in resultado["messages"]
                ):
                    logger.warning("turno_refusal turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="modelo_recusou"
                    )
                    AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    break

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
                    texto = _extrair_texto_do_turno(resultado["messages"])

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

                        # midias (04 §3.3 final): coleta as chamadas de `enviar_midia` deste
                        # turno em ordem de `call_idx` (ordinal injetado pelo no `tools`), p/
                        # o `enviar_turno` despachar apos os chunks de texto (05 §5).
                        res = await conn.execute(
                            """
                            SELECT payload->>'midia_id' AS midia_id,
                                   payload->>'legenda'  AS legenda
                              FROM barravips.tool_calls
                             WHERE turno_id = %s AND tool_name = 'enviar_midia'
                             ORDER BY call_idx
                            """,
                            (turno_id,),
                        )
                        midias: list[dict[str, Any]] = [dict(r) for r in await res.fetchall()]

                        # critico (07 §3 passo 8 / 05 §3): write tool COM EFEITO ja commitada --
                        # a msg ao cliente (chave Pix, confirmacao) nao pode ser cancelada nem
                        # perdida. pedir_pix SEMPRE conta; registrar_extracao so quando CAUSOU
                        # transicao (marcar toda registrar_extracao mataria o cancel). O flag
                        # vai no PAYLOAD do job (05 §7), nao no Redis -- TTL pode expirar antes
                        # da ultima retry com backoff.
                        res = await conn.execute(
                            """
                            SELECT 1 FROM barravips.tool_calls
                             WHERE turno_id = %s
                               AND ( tool_name = 'pedir_pix_deslocamento'
                                  OR ( tool_name = 'registrar_extracao'
                                       AND resultado->>'novo_estado' IS NOT NULL ) )
                             LIMIT 1
                            """,
                            (turno_id,),
                        )
                        critico = await res.fetchone() is not None

                    msg_ids_cliente: list[str] = [r["evolution_message_id"] for r in inbound]
                    chars_inbound = sum(len(r["conteudo"] or "") for r in inbound)

                    chunks, quote_flags = chunk_texto(texto)
                    # `[quote]` na bolha → cita a ULTIMA mensagem do cliente no turno
                    # (alvo natural de recusa/qualificacao/contraproposta). Sem inbound,
                    # o flag e ignorado (None) — defesa para canned/reengajamento.
                    alvo_quote = msg_ids_cliente[-1] if msg_ids_cliente else None
                    # texto do alvo p/ o `quoted.message.conversation` (balão de reply não
                    # fica vazio — a Evolution não faz lookup pelo id; verificado 2026-05-30).
                    alvo_quote_texto = inbound[-1]["conteudo"] if inbound else None
                    quote_msg_ids: list[str | None] = [
                        alvo_quote if flag else None for flag in quote_flags
                    ]
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
                            quote_msg_ids=quote_msg_ids,
                            quote_texto=alvo_quote_texto,
                        )
                        AGENTE_TURNO_RESULTADO.labels("ok").inc()
                        _amostrar_eval_online(chunks)  # EVAL-11: rubrica online amostrada

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
                        request_id=request_id,  # OBS-07: mantem correlacao no turno recuperado
                        _job_id=f"turno:{conversa_id}",
                        _defer_by=timedelta(seconds=2),
                    )
    except LockBusy:
        # contenda com rotear_imagem (06 §2.1) — re-defere curto via ctx["redis"] (ArqRedis).
        await redis.enqueue_job(
            "processar_turno",
            conversa_id=conversa_id,
            aguardar_transcricao=aguardar_transcricao,
            request_id=request_id,  # OBS-07: mantem correlacao no re-defer
            _job_id=f"turno:{conversa_id}",
            _defer_by=timedelta(seconds=2),
        )
        LOCK_OCUPADO.inc()


async def aguardar_transcricoes(redis: Any, conversa_id: str, *, orcamento_s: int = 8) -> bool:
    """BLPOP no canal `transcricao:{conversa_id}` (06 §1.4).

    O worker `transcrever_audio` faz `LPUSH` com `{"ok": true|false}` ao terminar. Multiplos
    audios consecutivos sao drenados (BLPOP em loop) ate esvaziar a fila no orcamento.
    Retorna False se:
      - estourou `orcamento_s` antes de ler qualquer sinal;
      - algum dos sinais lidos veio com `ok=false` (worker reportou falha definitiva).
    Retorna True quando todos os sinais lidos foram `ok=true`.

    Sem `asyncio.timeout` aqui (06 §1.4): redis-py expoe `blpop(timeout=...)` nativamente e o
    orcamento total e contado deduzindo o decorrido — assim varios audios curtos cabem nos 8s.
    Renomeado para evitar ASYNC109 (regra do ruff: arg `timeout` em funcao async sugere
    `asyncio.timeout` quando o que se quer e propagar pro syscall).
    """
    chave = f"transcricao:{conversa_id}"
    deadline = asyncio.get_event_loop().time() + orcamento_s
    leu_algum = False
    todos_ok = True
    while True:
        restante = deadline - asyncio.get_event_loop().time()
        if restante <= 0:
            break
        # blpop devolve None no timeout; lista de [chave, payload] caso contrario.
        res = await redis.blpop(chave, timeout=max(1, int(restante)))
        if res is None:
            break
        leu_algum = True
        # redis-py sem decode_responses devolve bytes; em fakeredis pode vir str.
        _, payload = res
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            logger.warning(
                "transcricao_payload_invalido conversa_id=%s payload=%r", conversa_id, payload
            )
            todos_ok = False
            continue
        if not data.get("ok", False):
            todos_ok = False
    return leu_algum and todos_ok


def _amostrar_eval_online(chunks: list[str]) -> None:
    """EVAL-11: amostra ~`eval_online_sample_rate` dos turnos 'ok' e observa a rubrica online de
    non_disclosure em `agente_eval_pass_rate{suite=online_non_disclosure}`.

    Rubrica DETERMINISTICA (`tem_marcador_ia`, mesma do output_guard) -> sem custo de LLM por
    turno amostrado. So observa um sinal de TENDENCIA (scraped por Prometheus em regime); o gate
    de verdade segue offline (runner). 0 ou falha de amostragem -> no-op silencioso.
    """
    rate = get_settings().eval_online_sample_rate
    if rate <= 0 or random.random() >= rate:  # noqa: S311 -- amostragem de telemetria, nao cripto
        return
    passou = 0.0 if tem_marcador_ia(" ".join(chunks)) else 1.0
    AGENTE_EVAL_PASS_RATE.labels("online_non_disclosure").observe(passou)


def _extrair_texto(msg: AIMessage) -> str:
    """Texto plano de uma AIMessage. content pode ser str ou lista de blocos (1.x)."""
    if isinstance(msg.content, str):
        return msg.content
    partes = [
        bloco.get("text", "")
        for bloco in msg.content
        if isinstance(bloco, dict) and bloco.get("type") == "text"
    ]
    return "".join(partes)


def _extrair_texto_do_turno(messages: list[BaseMessage]) -> str:
    """Agrega texto das AIMessages GERADAS pelo LLM neste turno, separadas por \\n\\n.

    No padrao ReAct, o LLM e chamado de novo depois de cada ToolMessage; quando ja respondeu
    o cliente na 1a passagem (texto + tool_call), a 2a passagem volta com `content=[]` —
    pegar so a ultima AIMessage daria "" e disparava `turno_sem_resposta`.

    O `prepare_context` re-injeta AIMessages historicas (mensagens previas da IA do banco)
    no input do LLM (`nos/prepare_context.py:188`); essas vem SEM `usage_metadata`. Filtrar
    por `usage_metadata` mantem so o que o LLM gerou agora — agregar historicas duplicaria
    a resposta anterior junto com a nova (bug observado em prod 2026-05-27).
    """
    partes = [
        _extrair_texto(m)
        for m in messages
        if isinstance(m, AIMessage) and m.usage_metadata is not None
    ]
    return "\n\n".join(p for p in partes if p)


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

    # Herda o vendedor padrão da modelo (ADR 0012): quando a IA conduz a modelo,
    # modelos.vendedor_id já é NULL → atendimento sem comissão, transição limpa.
    res = await conn.execute(
        """
        INSERT INTO barravips.atendimentos
          (cliente_id, modelo_id, conversa_id, estado, fonte_decisao_ultima_transicao, vendedor_id)
        SELECT c.cliente_id, c.modelo_id, c.id, 'Novo', 'extracao_ia', m.vendedor_id
          FROM barravips.conversas c
          JOIN barravips.modelos m ON m.id = c.modelo_id
         WHERE c.id = %s
        RETURNING *
        """,
        (conversa_id,),
    )
    novo = await res.fetchone()
    assert novo is not None  # INSERT ... RETURNING sempre devolve a linha criada
    return novo


async def resolver_atendimento_existente(
    conn: AsyncConnection[dict[str, Any]], conversa_id: UUID
) -> dict[str, Any] | None:
    """Le o atendimento aberto da conversa SEM criar (06 §2.1).

    Espelha `resolver_atendimento` mas e read-only — usado pelo `rotear_imagem` sob `lock:conv`
    para roteamento (sem efeito colateral): se a imagem chega numa conversa sem atendimento
    aberto, o caminho normal e fora-fluxo (a IA cria atendimento pelo turno, nao por imagem).
    """
    res = await conn.execute(
        """
        SELECT a.*
          FROM barravips.atendimentos a
         WHERE a.conversa_id = %s
           AND a.estado NOT IN ('Fechado', 'Perdido')
         ORDER BY a.created_at DESC
         LIMIT 1
        """,
        (conversa_id,),
    )
    row = await res.fetchone()
    return row


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

    A `abrir_handoff` shipada NAO aceita `motivo=` (09 §4.3): o motivo passa pelo `mapear_motivo`
    do servico de dominio (M3f) -> `(tipo, responsavel)` e o motivo literal vai em `observacao`.
    Os motivos de exaustao (`timeout_grafo`/`exaustao_iteracoes`/`modelo_recusou`) caem em
    `tipo=outro` + `responsavel="Fernando"` — comportamento identico ao hardcode anterior.
    A metrica `agente_escalada_total` e emitida aqui (camada do agente), nao em `abrir_handoff`.
    """
    from barra.dominio.escaladas.service import abrir_handoff, mapear_bucket, mapear_motivo

    tipo, responsavel = mapear_motivo(motivo)
    async with pool.connection() as conn:
        await abrir_handoff(
            conn,
            atendimento_id=atendimento_id,
            responsavel=responsavel,
            tipo=tipo,
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
    AGENTE_ESCALADA.labels(mapear_bucket(motivo), motivo).inc()


async def despachar_humanizacao(
    ctx: dict[str, Any],
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict[str, Any]],
    msg_ids_cliente: list[str],
    chars_inbound: int,
    critico: bool,
    quote_msg_ids: list[str | None] | None = None,
    quote_texto: str | None = None,
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
        quote_msg_ids=quote_msg_ids,
        quote_texto=quote_texto,
        _job_id=f"turno_envio:{turno_id}",
    )
