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
import re
import unicodedata
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid5

import structlog
from anthropic import APIStatusError, APITimeoutError, RateLimitError
from langchain_core.messages import AIMessage
from langfuse import Langfuse, get_client
from langgraph.errors import GraphRecursionError
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.agente._canned import escolher_canned_transcricao_falhou
from barra.agente._custo import custo_chat_turno_brl
from barra.agente._texto_turno import extrair_texto_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.nos.output_guard import (
    tem_marcador_ia,
    tem_marcador_outro_cliente,
    tem_marcador_system,
)
from barra.agente.persona import _brl
from barra.core.metrics import (
    AGENTE_ESCALADA,
    AGENTE_EVAL_PASS_RATE,
    AGENTE_TURNO_DURACAO,
    AGENTE_TURNO_RESULTADO,
    LOCK_OCUPADO,
    QUOTE_RESOLUCAO,
)
from barra.core.redis import LockBusy, adquirir_lock
from barra.core.tracing import langfuse_handler, metadata_trace_turno, registrar_feedback_online
from barra.settings import get_settings
from barra.webhook.despacho import enfileirar_processar_turno
from barra.workers._chunking import MAX_CHARS, chunk_texto

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


def _formatar_bolha_pix(chave: str, titular: str | None, valor: Any) -> str:
    """Bolha determinística com os dados do Pix de deslocamento, anexada após o texto da IA.

    A tool `pedir_pix_deslocamento` mantém a chave (string crítico) FORA do LLM e promete que o
    sistema a anexa (agente/ferramentas/pix.py). É aqui que isso acontece: lemos a chave fresh do
    cadastro e formamos uma bolha objetiva (sem termo de carinho, no estilo de mensagem de dado).
    """
    linhas = [f"chave pix: {chave}"]
    if titular:
        linhas.append(f"em nome de {titular}")
    linhas.append(f"valor: {_brl(valor)}")
    return "\n".join(linhas)


def _norm_quote(texto: str) -> str:
    """Normaliza para o match de trecho: colapsa espaços, casefold e remove acentos.

    O LLM copia o texto do cliente, mas costuma soltar diacríticos do PT-BR ao recortar o trecho
    (`horario` por `horário`, `voce` por `você`). Dobrar via NFKD + drop de combining marks deixa o
    match acento-insensível, evitando o fallback-para-última justo no caso de desambiguação.
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.split()).casefold()


def _resolver_quotes(
    quote_alvos: list[str | None],
    inbound: list[dict[str, Any]],
) -> tuple[list[str | None], list[str | None]]:
    """Casa cada alvo de quote (saída de `chunk_texto`) com a mensagem do cliente alvo.

    Devolve dois lists paralelos aos chunks: `(quote_msg_ids, quote_textos)`, onde cada posição é
    o `evolution_message_id` e o `conteudo` (texto do balão, p/ `quoted.message.conversation` — a
    Evolution não faz lookup pelo id; verificado 2026-05-30) da mensagem citada, ou `None`.

    Por alvo:
    - `None` → sem quote;
    - `""` (`[quote]` puro) → última mensagem do cliente do turno;
    - `"trecho"` (`[quote: trecho]`) → a ÚLTIMA inbound cujo conteúdo contém o trecho; miss →
      fallback gracioso para a última mensagem (nunca trava o turno).

    Sem inbound, todo alvo vira `None` (defesa para canned/reengajamento).
    """
    msg_ids: list[str | None] = []
    textos: list[str | None] = []
    ultimo = inbound[-1] if inbound else None
    for alvo in quote_alvos:
        if alvo is None or ultimo is None:
            msg_ids.append(None)
            textos.append(None)
            continue
        escolhido = ultimo
        if alvo == "":
            QUOTE_RESOLUCAO.labels("ultima").inc()
        else:
            trecho = _norm_quote(alvo)
            casados = [r for r in inbound if trecho in _norm_quote(r["conteudo"] or "")]
            if casados:
                escolhido = casados[-1]
                QUOTE_RESOLUCAO.labels("ok").inc()
            else:
                QUOTE_RESOLUCAO.labels("miss").inc()  # fallback p/ última
        msg_ids.append(escolhido["evolution_message_id"])
        textos.append(escolhido["conteudo"])
    return msg_ids, textos


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
            # Gate de pendencia: sem `pending:conv` nao ha mensagem nova — outro job ja consumiu
            # a janela (ex.: o de varredura, ver webhook/despacho.py). Rodar o grafo mesmo assim
            # geraria double-texting: a janela termina na propria fala da IA e o LLM emendaria
            # outra bolha. So no 1o loop; nos seguintes o passo 8 ja exige pending cheio.
            if not await redis.get(f"pending:conv:{conversa_id}"):
                logger.info("turno_sem_pendencia conversa_id=%s", conversa_id)
                AGENTE_TURNO_RESULTADO.labels("sem_pendencia").inc()
                return
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
                #      SDK + o ramo modelo_indisponivel; este teto e a parte.
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
                #    metadata/tags de trace (modelo_id/atendimento_id, este como gen_ai.conversation.id)
                #    escopam o trace do LangSmith — sem isso o trace de prod so tinha thread_id e nao
                #    dava p/ agrupar por atendimento (os IDs vao so no config, nao tocam o cache).
                config: dict[str, Any] = {
                    "configurable": {"thread_id": conversa_id},
                    "recursion_limit": RECURSION_LIMIT,
                    **metadata_trace_turno(str(atendimento["modelo_id"]), str(atendimento["id"])),
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
                # Langfuse (ADR 0019): trace-id determinístico por turno (seed=turno_id) — evita o
                # `handler.last_trace_id` racy num worker que processa turnos concorrentes. Embrulha o
                # ainvoke num span com esse trace_id p/ o CallbackHandler pendurar o grafo nele; o
                # mesmo id ancora o score online (EVAL-11). None se o tracing esta desligado.
                lf_handler = langfuse_handler()
                trace_id_eval: str | None = None
                callbacks: list[Any] = []
                span_ctx: AbstractContextManager[Any] = nullcontext()
                if lf_handler is not None:
                    trace_id_eval = Langfuse.create_trace_id(seed=turno_id)
                    callbacks = [lf_handler]
                    span_ctx = get_client().start_as_current_observation(
                        as_type="span", name="turno", trace_context={"trace_id": trace_id_eval}
                    )
                try:
                    with span_ctx:
                        resultado = await asyncio.wait_for(
                            graph.ainvoke(
                                entrada,
                                config={**config, "callbacks": callbacks},
                                context=context,
                            ),
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
                    # generico abaixo, que mataria o turno sem escalada (o ARQ NAO retenta excecao
                    # comum — so `Retry` explicito ou shutdown do worker).
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

                # 5a'. custo do turno acumulado no atendimento (OBS go-live): ANTES do descarte do
                #      passo 6 — turno descartado tambem queimou tokens. Best-effort: telemetria
                #      nunca derruba o turno.
                await acumular_custo_atendimento(
                    pool,
                    atendimento["id"],
                    custo_chat_turno_brl(resultado["messages"], settings.usd_brl_cotacao),
                )

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

                # 5c. STOP-03/06: tool_use truncado (max_tokens / janela de contexto) -> args
                #     possivelmente incompletos; o no llm NAO despachou a tool. Escala falha de
                #     capacidade (modelo_truncado) e encerra SEM bolha crua, igual ao refusal. Raro
                #     (premissa: max_tokens=1024 nao trunca, 03 §6.1).
                if any(
                    isinstance(m, AIMessage)
                    and m.usage_metadata is not None
                    and (m.response_metadata or {}).get("stop_reason")
                    in ("max_tokens", "model_context_window_exceeded")
                    and bool(m.tool_calls)
                    for m in resultado["messages"]
                ):
                    logger.warning("turno_truncado turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="modelo_truncado"
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
                    texto = extrair_texto_do_turno(resultado["messages"])

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

                        # Pix de deslocamento (bug F): a tool `pedir_pix_deslocamento` NÃO devolve
                        # a chave (string crítico fora do LLM, agente/ferramentas/pix.py) e promete
                        # que o sistema a anexa. Só consultamos quando o turno é `critico` —
                        # pedir_pix SEMPRE torna o turno crítico, então o turno comum (sem write
                        # tool) pula a query. Lemos chave/titular fresh do cadastro + o valor que a
                        # tool registrou, p/ anexar a bolha do Pix após o texto da IA.
                        pix_row: dict[str, Any] | None = None
                        if critico:
                            res = await conn.execute(
                                """
                                SELECT mo.chave_pix, mo.titular_chave, tc.payload->>'valor' AS valor
                                  FROM barravips.tool_calls tc
                                  JOIN barravips.modelos mo ON mo.id = %s
                                 WHERE tc.turno_id = %s
                                   AND tc.tool_name = 'pedir_pix_deslocamento'
                                 LIMIT 1
                                """,
                                (atendimento["modelo_id"], turno_id),
                            )
                            pix_row = await res.fetchone()

                    msg_ids_cliente: list[str] = [r["evolution_message_id"] for r in inbound]
                    chars_inbound = sum(len(r["conteudo"] or "") for r in inbound)

                    chunks, quote_alvos = chunk_texto(texto)
                    # casa cada alvo de `[quote]` com (evolution_message_id, texto do balão) da
                    # mensagem do cliente alvo. `[quote: trecho]` busca a msg que contém o trecho;
                    # `[quote]` puro pega a última. Sem inbound, o alvo é ignorado (None).
                    quote_msg_ids, quote_textos = _resolver_quotes(quote_alvos, inbound)
                    # Anexa a bolha do Pix (bug F) como ÚLTIMA bolha do turno, sem quote. Quando o
                    # turno pediu Pix ele já é `critico` (não-cancelável), então a chave sempre sai.
                    if pix_row and pix_row.get("chave_pix"):
                        chunks = [
                            *chunks,
                            _formatar_bolha_pix(
                                pix_row["chave_pix"],
                                pix_row.get("titular_chave"),
                                pix_row.get("valor") or settings.pix_deslocamento_valor,
                            ),
                        ]
                        quote_msg_ids = [*quote_msg_ids, None]
                        quote_textos = [*quote_textos, None]
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
                            quote_textos=quote_textos,
                        )
                        AGENTE_TURNO_RESULTADO.labels("ok").inc()
                        # EVAL-11: rubricas online amostradas (1 sorteio, 4 suites) -> Prometheus
                        # (tendencia) + scores no trace do Langfuse (veredito por-turno legivel).
                        scores_online = _amostrar_eval_online(chunks)
                        if scores_online is not None and trace_id_eval is not None:
                            for suite, score in scores_online.items():
                                await asyncio.to_thread(
                                    registrar_feedback_online,
                                    trace_id_eval,
                                    suite,
                                    score,
                                )

                # 8. drena: chegou msg com o lock retido? re-roda sob o MESMO lock; senao sai.
                if not await redis.get(f"pending:conv:{conversa_id}"):
                    break
            else:
                # teto de drain estourado com pending ainda cheio -> re-enfileira (libera o lock).
                # Evita prender um worker slot num cliente tagarela. NB: enqueue direto com o
                # `_job_id` estatico seria no-op aqui — a job_key DESTE job ainda existe ate o
                # finish_job — por isso o helper com fallback de varredura (webhook/despacho.py).
                if await redis.get(f"pending:conv:{conversa_id}"):
                    await enfileirar_processar_turno(
                        redis,
                        conversa_id,
                        aguardar_transcricao=False,
                        request_id=request_id,  # OBS-07: mantem correlacao no turno recuperado
                        defer_s=2,
                    )
    except LockBusy:
        # contenda com rotear_imagem (06 §2.1) — re-defere curto via ctx["redis"] (ArqRedis).
        # Mesmo caso do MAX_DRAIN: o `_job_id` estatico pode ser o NOSSO -> helper com fallback.
        await enfileirar_processar_turno(
            redis,
            conversa_id,
            aguardar_transcricao=aguardar_transcricao,
            request_id=request_id,  # OBS-07: mantem correlacao no re-defer
            defer_s=2,
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


# Marcador residual de template numa bolha final: prefixo [quote...] que o chunking deveria ter
# extraido, cerca de codigo ou heading markdown — sinal de regressao de prompt/chunking que
# escapou para o cliente.
_MARCADOR_TEMPLATE = re.compile(r"\[quote|```|^#{1,3}\s", re.MULTILINE)


def _formato_bolha_ok(chunks: list[str]) -> bool:
    """Rubrica online de formato (PURA): nenhuma bolha vazia, nenhuma acima de MAX_CHARS do
    chunking e sem marcador residual de template."""
    if not chunks:
        return False
    for c in chunks:
        if not c.strip() or len(c) > MAX_CHARS or _MARCADOR_TEMPLATE.search(c):
            return False
    return True


def _amostrar_eval_online(chunks: list[str]) -> dict[str, float] | None:
    """EVAL-11: amostra ~`eval_online_sample_rate` dos turnos 'ok' e observa as rubricas online
    DETERMINISTICAS em `agente_eval_pass_rate{suite=...}` — sem custo de LLM por turno amostrado.

    Um UNICO sorteio cobre as 4 suites (mesmo turno amostrado para todas — comparaveis entre si):
      - `online_non_disclosure`  — `tem_marcador_ia` (auto-referencia de IA);
      - `online_system_leak`    — `tem_marcador_system` (fragmento de system/persona);
      - `online_segredo_agenda` — `tem_marcador_outro_cliente` ("estou com outro cliente");
      - `online_formato_bolha`  — `_formato_bolha_ok` (vazia/estourada/template residual).
    As tres primeiras reusam os regexes do output_guard (fonte unica) e cobrem exatamente os
    caminhos que PULAM o no output_guard (canned do intercept, bolha anexada pelo coordenador).

    So observa sinal de TENDENCIA (Prometheus): nao bloqueia nem reprova turno (o gate offline
    via runner foi removido — hoje EVAL-11 e a unica checagem automatica de invariantes). Devolve
    {suite: score 0.0/1.0} quando amostrou, p/ o caller anexar como feedback no trace do Langfuse;
    None quando nao amostrou (rate=0 ou sorteio acima da taxa).
    """
    rate = get_settings().eval_online_sample_rate
    if rate <= 0 or random.random() >= rate:  # noqa: S311 -- amostragem de telemetria, nao cripto
        return None
    texto = " ".join(chunks)
    scores = {
        "online_non_disclosure": 0.0 if tem_marcador_ia(texto) else 1.0,
        "online_system_leak": 0.0 if tem_marcador_system(texto) else 1.0,
        "online_segredo_agenda": 0.0 if tem_marcador_outro_cliente(texto) else 1.0,
        "online_formato_bolha": 1.0 if _formato_bolha_ok(chunks) else 0.0,
    }
    for suite, score in scores.items():
        AGENTE_EVAL_PASS_RATE.labels(suite).observe(score)
    return scores


async def acumular_custo_atendimento(
    pool: AsyncConnectionPool[Any], atendimento_id: UUID, custo_brl: float
) -> None:
    """Acumula o custo de chat do turno em `atendimentos.custo_ia_brl` (OBS go-live).

    UPDATE acumulativo atomico (`custo_ia_brl + %s`) — race-safe por construcao, e o turno ja
    roda sob `lock:conv` (escritor unico). BEST-EFFORT, mesmo contrato de
    `registrar_feedback_online`: telemetria nunca derruba o turno (falha vira warning).
    `custo_brl <= 0` (sem usage medivel) -> no-op.

    O `conn.transaction()` confina a falha num SAVEPOINT: se o UPDATE estourar (ex.: migration
    `custo_ia_brl` ainda nao aplicada nesse banco), so o savepoint e desfeito — uma transacao
    externa compartilhada (pool-de-uma-conexao dos testes needs_db) NAO fica abortada.
    """
    if custo_brl <= 0:
        return
    try:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE barravips.atendimentos SET custo_ia_brl = custo_ia_brl + %s WHERE id = %s",
                (custo_brl, atendimento_id),
            )
    except Exception:
        logger.warning(
            "custo_persistencia_falhou atendimento_id=%s custo_brl=%s",
            atendimento_id,
            custo_brl,
            exc_info=True,
        )


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
    quote_textos: list[str | None] | None = None,
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
        quote_textos=quote_textos,
        _job_id=f"turno_envio:{turno_id}",
    )
