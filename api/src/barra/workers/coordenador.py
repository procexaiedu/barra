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
from collections.abc import Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid5

import structlog
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langfuse import Langfuse, get_client
from langgraph.errors import GraphRecursionError
from openai import APIStatusError as OpenAIAPIStatusError
from openai import APITimeoutError as OpenAIAPITimeoutError
from openai import RateLimitError as OpenAIRateLimitError
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.agente._canned import escolher_canned_transcricao_falhou
from barra.agente._custo import custo_chat_turno_brl
from barra.agente._parceria import formatar_bolha_contato_parceira
from barra.agente._texto_turno import (
    desfecho_do_turno,
    extrair_texto_do_turno,
    mensagens_cliente_do_turno,
    mensagens_do_turno,
    raciocinio_do_turno,
    tags_do_turno,
)
from barra.agente._versao import regime_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.nos.output_guard import (
    tem_marcador_ia,
    tem_marcador_outro_cliente,
    tem_marcador_system,
)
from barra.agente.persona import brl
from barra.core.llm import PARADA_RECUSA, PARADA_TRUNCADA, motivo_parada
from barra.core.metrics import (
    AGENTE_ESCALADA,
    AGENTE_EVAL_PASS_RATE,
    AGENTE_TURNO_DURACAO,
    AGENTE_TURNO_RESULTADO,
    ENVIO_DEFER_HUMANO,
    LOCK_OCUPADO,
    QUOTE_RESOLUCAO,
)
from barra.core.redis import LockBusy, adquirir_lock
from barra.core.tracing import (
    langfuse_handler,
    metadata_trace_turno,
    registrar_feedback_online,
    resumir_trace_turno,
)
from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA
from barra.dominio.modelos.parcerias import contato_da_parceira
from barra.settings import get_settings
from barra.webhook.despacho import enfileirar_processar_turno
from barra.workers._chunking import MAX_CHARS, chunk_texto
from barra.workers.envio import amostrar_defer_humano_s

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

# Descricao humana por motivo de exaustao, p/ o resumo_operacional do handoff
# (escalar_por_exaustao). Antes o resumo dizia "estourou recursion_limit ou excedeu 60s" para
# TODO motivo -- mentindo p/ teto_turnos / modelo_indisponivel / modelo_recusou / modelo_truncado,
# que nada tem a ver com recursion/timeout. Fallback generico p/ motivo novo nao mapeado.
_DESCRICAO_EXAUSTAO: dict[str, str] = {
    "exaustao_iteracoes": (
        f"estourou o recursion_limit ({RECURSION_LIMIT} super-steps "
        f"~= {RECURSION_LIMIT // 2} round-trips llm<->tools)"
    ),
    "timeout_grafo": "excedeu o teto de 60s de execucao do turno",
    "teto_turnos": f"atingiu o teto de {TETO_TURNOS_DIA} turnos no dia para a conversa (CUSTO-04)",
    "modelo_indisponivel": (
        "o provider do LLM ficou indisponivel (5xx/timeout apos os retries do SDK)"
    ),
    "modelo_recusou": "o LLM recusou a geracao (safety filter do provider)",
    "modelo_truncado": "a resposta do LLM truncou (max_tokens/janela de contexto) com tool_use incompleto",
    "erro_interno": "quebrou com uma excecao nao prevista no meio do turno (bug, nao falha de provider)",
}

# Janela NAO respondida da conversa: mensagens do cliente com `created_at` DEPOIS da ultima bolha
# da IA. Predicado unico, usado em dois lugares — o read receipt/quote do passo 7 (QUAIS sao) e o
# fallback do gate de pendencia (EXISTE alguma?). Por construcao ele ja e o anti-double-texting:
# se a IA falou por ultimo, o resultado e vazio.
_WHERE_INBOUND_NAO_RESPONDIDO = """
     WHERE conversa_id = %s AND direcao = 'cliente'
       AND created_at > COALESCE(
             (SELECT max(created_at) FROM barravips.mensagens
               WHERE conversa_id = %s AND direcao = 'ia'), 'epoch')
"""


# O turno e CRITICO? (07 §3 passo 8 / 05 §3): write tool COM EFEITO ja commitada -- a msg ao
# cliente (chave Pix, confirmacao) nao pode ser cancelada nem perdida. `registrar_extracao` so conta
# quando CAUSOU transicao (marcar toda registrar_extracao mataria o cancel) OU solicitou o Pix de
# deslocamento (`pix_solicitado` ocorre sem nova transicao, `novo_estado` NULL).
# SQL em constante porque DOIS caminhos o rodam: o despacho normal e o resgate do turno DESCARTADO
# (`_despachar_criticas_do_descarte`) -- e eles tem de decidir "critico" pelo mesmo criterio.
_SQL_TURNO_CRITICO = """
SELECT 1 FROM barravips.tool_calls
 WHERE turno_id = %s
   AND tool_name = 'registrar_extracao'
   AND ( resultado->>'novo_estado' IS NOT NULL
      OR resultado->>'pix_solicitado' = 'true' )
 LIMIT 1
"""
# Pix de deslocamento: a solicitacao deterministica (registrar_extracao, dominio/atendimentos)
# NAO grava a chave (string critica fora do LLM) -- so o valor em `pix_valor`, e promete que o
# sistema anexa a chave. Chave/titular lidos FRESH do cadastro.
_SQL_PIX_DO_TURNO = """
SELECT mo.chave_pix, mo.titular_chave,
       tc.resultado->>'pix_valor' AS valor
  FROM barravips.tool_calls tc
  JOIN barravips.modelos mo ON mo.id = %s
 WHERE tc.turno_id = %s
   AND tc.tool_name = 'registrar_extracao'
   AND tc.resultado->>'pix_solicitado' = 'true'
 LIMIT 1
"""


def _formatar_bolha_pix(chave: str, titular: str | None, valor: Any) -> str:
    """Bolha determinística com os dados do Pix de deslocamento, anexada após o texto da IA.

    A solicitação determinística de Pix (registrar_extracao, dominio/atendimentos/service.py)
    mantém a chave (string crítico) FORA do LLM e promete que o sistema a anexa. É aqui que isso
    acontece: lemos a chave fresh do cadastro e formamos uma bolha objetiva (sem termo de carinho,
    no estilo de mensagem de dado).
    """
    linhas = [f"chave pix: {chave}"]
    if titular:
        linhas.append(f"em nome de {titular}")
    linhas.append(f"valor: {brl(valor)}")
    return "\n".join(linhas)


# Marcadores de "estou enviando" — uma bolha curta com qualquer um deles, antes da bolha
# determinística do Pix, é pré-anúncio redundante ("mandando por aqui", "segue"): a chave já sai
# logo abaixo. Não casa o ENQUADRAMENTO do pedido ("me manda o pixzinho do deslocamento"), que é
# legítimo e excluído por _eh_pre_anuncio_pix.
_MARCADORES_ENVIO_PIX = (
    "mandando",
    "segue",
    "ta aqui",
    "aqui ta",
    "aqui esta",
    "aqui vai",
    "ai vai",
    "ai esta",
    "ja te mando",
    "te mando",
    "vou mandar",
    "vou te mandar",
)
_EXCLUI_PRE_ANUNCIO_PIX = ("deslocament", "pixzinho", "me manda", "preciso", "manda o", "manda a")


def _eh_pre_anuncio_pix(texto: str) -> bool:
    """A última bolha de texto da IA, antes da bolha do Pix, é só pré-anúncio de envio?

    Rede de segurança determinística (a correção primária é o prompt): a tool não devolve a chave,
    mas o prompt induzia a IA a "escrever com a chave", produzindo uma ponte vazia ("mandando por
    aqui 🥰") redundante com a bolha que o coordenador anexa. Descartamos essa ponte. Conservador:
    só bolha CURTA, com marcador de envio e SEM enquadramento do pedido (que deve sobreviver)."""
    norm = _norm_quote(texto)
    if not norm or len(norm) > 35:
        return False
    if any(t in norm for t in _EXCLUI_PRE_ANUNCIO_PIX):
        return False
    return any(m in norm for m in _MARCADORES_ENVIO_PIX)


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


async def _despachar_criticas_do_descarte(
    ctx: dict[str, Any],
    pool: Any,
    *,
    conversa_id: str,
    turno_id: str,
    modelo_id: Any,
    atendimento_id: Any,
) -> bool:
    """O turno foi DESCARTADO — resgata as bolhas DETERMINISTICAS que o sistema ja prometeu.

    Duas invariantes colidiam e uma engolia a outra (loop-massa r3, achado 6): "bolha zerada pelo
    guard nunca sai" e "bolha critica nunca se perde". O bloco que monta a chave Pix vivia INTEIRO
    dentro do `else:` do descarte, entao um turno que fechou a venda -- `pix_solicitado`, bloqueio
    reservado, estado em `Aguardando_confirmacao` -- e cujo TEXTO o guard reprovou saia com ZERO
    mensagens ao cliente que acabara de fechar: o banco andou, a conversa parou
    (`decidido_rapido_a` t5).

    O corte que dispensa decisao de produto: aqui NUNCA sai texto do modelo -- so a bolha que o
    SISTEMA gera (chave Pix lida fresh do cadastro, nunca do LLM), e so quando o turno e `critico`
    pelo mesmo criterio do caminho normal (`_SQL_TURNO_CRITICO`). A bolha critica ja e imune ao
    gate de pausa do envio por desenho (`workers/envio.py`: `checar_pausa = not critico and ...`),
    entao isto nao afrouxa nada -- so para de perder o que o proprio sistema garantiu.

    Devolve True quando despachou algo.
    """
    async with pool.connection() as conn:
        res = await conn.execute(_SQL_TURNO_CRITICO, (turno_id,))
        if await res.fetchone() is None:
            return False
        res = await conn.execute(_SQL_PIX_DO_TURNO, (modelo_id, turno_id))
        pix_row = await res.fetchone()
    if not (pix_row and pix_row.get("chave_pix")):
        # Critico por transicao de estado, sem bolha deterministica a anexar: nada a resgatar
        # (a confirmacao em si era texto do modelo, e texto do modelo continua barrado).
        return False
    chunks = [
        _formatar_bolha_pix(
            pix_row["chave_pix"],
            pix_row.get("titular_chave"),
            pix_row.get("valor") or get_settings().pix_deslocamento_valor,
        )
    ]
    logger.warning(
        "turno_descartado_com_critico atendimento_id=%s turno_id=%s -> despacha so a bolha"
        " deterministica (Pix)",
        atendimento_id,
        turno_id,
    )
    await despachar_humanizacao(
        ctx,
        conversa_id,
        turno_id,
        chunks,
        [],
        [],
        0,
        True,  # critico: nunca adia e pula o cancel-on-new-message
        defer_humano=False,
        ignorar_pausa=True,
    )
    return True


def pausa_aberta_por_este_turno(messages: Sequence[BaseMessage]) -> bool:
    """A `ia_pausada=true` que o passo 6 relê foi aberta POR ESTE TURNO — ou veio de fora?

    Discriminador do gate de pausa do envio (`ignorar_pausa`). O ESTADO DO BANCO não separa os
    dois casos: `ia_pausada` é o mesmo bit quando o agente escalou de propósito (e precisa
    entregar a bolha de espera) e quando um pipeline sem lock (foto de portaria, Pix, pausa manual
    do operador) pausou no meio do turno — e nesse segundo caso a modelo humana já está assumindo,
    então QUALQUER bolha da IA sai por cima dela.

    Nem o `ia_pausada_motivo` serve: `abrir_handoff` grava `handoff_ia` tanto para o `escalar` da
    IA quanto para o handoff MANUAL do operador (ADR-0032, `_pausar_ia`) — exatamente o caso
    "a IA respondeu algo não legal, eu assumo agora", onde calar é obrigatório. E o snapshot de
    `ia_pausada` no INÍCIO do turno também não: o gate do passo 2 garante que ele é sempre `false`
    (turno já pausado nem roda), então "pausa nova" não distingue nada.

    O que distingue é o RASTRO DO PRÓPRIO TURNO, lido do resultado do grafo — sem I/O, sem
    depender de timing e com o mesmo critério que o `post_process` usa para decidir se preserva a
    fala pré-`escalar` (agente/nos/post_process.py):

    - `escalar` executada com SUCESSO neste turno (tool_call casada com a ToolMessage; erro
      recuperável não conta — tool que falhou não abriu pausa nenhuma);
    - guarda de `registrar_extracao` que escala por dentro (a "escalada silenciosa" do piso de
      desconto / tipo não aceito / reagendamento), reconhecida pelo texto EXATO de
      `MENSAGENS_GUARD_ESCALADA` — a mesma igualdade que o `post_process` usa.

    Sem rastro => trata como pausa EXTERNA (falha para o lado seguro: na dúvida, não envia).
    """
    ids_escalar = {
        tc["id"]
        for m in mensagens_do_turno(messages)
        for tc in (m.tool_calls or [])
        if tc.get("name") == "escalar" and tc.get("id")
    }
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        conteudo = str(m.content)
        if conteudo in MENSAGENS_GUARD_ESCALADA:
            return True
        # mesmo par de sinais de erro do `extrair_texto_do_turno` (status do ToolNode + prefixo
        # "ERRO:" das tools com handle_tool_error).
        errou = m.status == "error" or conteudo.startswith("ERRO:")
        if m.tool_call_id in ids_escalar and not errou:
            return True
    return False


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
    # Label da metrica de duracao = modelo do chat ao vivo (DeepSeek V4 Flash direto).
    modelo_chat = settings.deepseek_model_chat
    tipo_turno = "audio" if aguardar_transcricao else "texto"

    # O lock contende SO com rotear_imagem (06 §2.1). Ocupado -> re-defere curto; o pending ja
    # foi setado por enfileirar_turno, entao ao re-disparar o turno le a janela inteira.
    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            # Gate de pendencia: sem `pending:conv` a hipotese e que outro job ja consumiu a
            # janela (ex.: o de varredura, ver webhook/despacho.py) — rodar o grafo mesmo assim
            # geraria double-texting: a janela terminaria na propria fala da IA e o LLM emendaria
            # outra bolha. Mas o Redis e so COALESCING, nao fonte de verdade do "ha trabalho": o
            # proprio turno apaga o `pending` ANTES de processar, entao toda retomada com ele ja
            # limpo (retry pos-crash — o ARQ so retenta `Retry` explicito, mas o shutdown do
            # worker re-enfileira —, varredura, TTL expirado) caia aqui e devolvia o cliente ao
            # vacuo. Quem responde "ha trabalho?" e o BANCO. So no 1o loop; nos seguintes o passo
            # 8 ja exige pending cheio.
            if not await redis.get(f"pending:conv:{conversa_id}"):
                if not await _fallback_tem_trabalho(pool, redis, ctx, conv_uuid, conversa_id):
                    logger.info("turno_sem_pendencia conversa_id=%s", conversa_id)
                    AGENTE_TURNO_RESULTADO.labels("sem_pendencia").inc()
                    return
                logger.warning(
                    "turno_recuperado_sem_pendencia conversa_id=%s", conversa_id
                )  # inbound orfao: o Redis perdeu a janela, o banco a devolveu
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
                        # Marca o turno atual ANTES do despacho (cancel-on-new-message, 05 §3.1): o
                        # canned vai critico=False, entao `enviar_turno` so o envia se
                        # turno_atual==turno_id. O set normal (passo 3) NAO roda neste branch (break
                        # abaixo), entao sem este set turno_atual fica no valor do turno ANTERIOR e o
                        # canned e abortado -> cliente sem o aviso de audio falho.
                        await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)
                        canned = escolher_canned_transcricao_falhou(seed=turno_id)
                        # defer_humano=False: o cliente acabou de mandar um áudio e espera reação;
                        # o pipeline já gastou debounce + BLPOP de 8s — adiar o aviso 40-90s por
                        # cima leria como sumiço, não como humano.
                        await despachar_humanizacao(
                            ctx,
                            conversa_id,
                            turno_id,
                            chunks=[canned],
                            midias=[],
                            msg_ids_cliente=[],
                            chars_inbound=0,
                            critico=False,
                            defer_humano=False,
                        )
                        # Encerra o turno atual; nao re-roda drain (canned ja respondeu).
                        break

                # 3. marca o turno atual — cancel-on-new-message (05 §3.1): o enviar_turno do turno
                #    anterior compara turno_atual e aborta os chunks pendentes ao ser superado.
                await redis.set(f"turno_atual:{conversa_id}", turno_id, ex=600)

                # 4. config (thread_id + recursion_limit, nativos do LangGraph) + context (deps e
                #    ids de escopo via Runtime Context API — 04 §1.1). prepare_context monta o
                #    prompt do zero dentro do grafo (03 §7), entrada vai vazia.
                #    metadata/tags de trace (modelo_id/atendimento_id/cliente_id, o atendimento como
                #    gen_ai.conversation.id) escopam o trace do LangSmith — sem isso o trace de prod so
                #    tinha thread_id e nao dava p/ agrupar/filtrar (os IDs vao so no config, nao tocam o cache).
                config: dict[str, Any] = {
                    "configurable": {"thread_id": conversa_id},
                    "recursion_limit": RECURSION_LIMIT,
                    **metadata_trace_turno(
                        str(atendimento["modelo_id"]),
                        str(atendimento["id"]),
                        str(atendimento["cliente_id"]),
                        # Carimbo do REGIME que produziu este turno (modelo + thinking + hash dos
                        # prompts): vira tag filtravel no trace — sem ele nao da p/ separar traces de
                        # antes/depois de uma edicao de prompt nem de um flip de thinking.
                        regime=regime_do_turno(settings),
                    ),
                }
                context = ContextAgente(
                    db_pool=pool,
                    redis=redis,
                    modelo_id=str(atendimento["modelo_id"]),
                    atendimento_id=str(atendimento["id"]),
                    cliente_id=str(atendimento["cliente_id"]),
                    turno_id=turno_id,
                    # Clock injection: ausente no ctx do worker real (-> None -> relogio do banco,
                    # prod inalterada); o harness fiel injeta `agora_override` p/ fixar o relogio do
                    # turno e tornar agenda/bordas deterministicas.
                    agora_utc=ctx.get("agora_override"),
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
                    with span_ctx as turno_span:
                        resultado = await asyncio.wait_for(
                            graph.ainvoke(
                                entrada,
                                config={**config, "callbacks": callbacks},
                                context=context,
                            ),
                            # Teto do TURNO. Vem do settings junto com `llm_timeout_s` (teto por
                            # CHAMADA de LLM, estritamente menor): com os dois em 60.0 literais a
                            # chamada pendurada morria aqui, fora do grafo, onde so existe handoff
                            # — nunca no guard, que tem fallback deterministico pronto.
                            timeout=settings.turno_timeout_s,
                        )
                        # Observabilidade (ADR 0019): ainda com o span vivo, torna o ROOT span
                        # autossuficiente — msg do cliente no input, resposta + desfecho (mecanica:
                        # extracao/erro/reoferta) no output, level=WARNING se a extracao errou. Sem
                        # isto o trace nasce input/output nulos e quem opera garimpa ~20 observations.
                        desfecho_turno = desfecho_do_turno(resultado)
                        resumir_trace_turno(
                            turno_span,
                            entrada=mensagens_cliente_do_turno(resultado),
                            resposta=extrair_texto_do_turno(resultado["messages"]),
                            desfecho=desfecho_turno,
                            # O raciocinio do thinking (default "low" em prod) ao lado da fala: e o
                            # que explica a fala, e sem isto ficaria enterrado no additional_kwargs
                            # de uma generation no meio do grafo.
                            raciocinio=raciocinio_do_turno(resultado),
                            # Tags do TRACE: as de escopo/regime (ja no config) MAIS as do que
                            # aconteceu. Tem que ir o conjunto completo — escrever o atributo
                            # substitui a lista, nao soma.
                            tags=[*config["tags"], *tags_do_turno(resultado)],
                            level="WARNING" if desfecho_turno.get("erros_tool") else "DEFAULT",
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
                except (
                    OpenAIRateLimitError,
                    OpenAIAPITimeoutError,
                    OpenAIAPIStatusError,
                ):
                    # 5xx/timeout persistente da API do LLM (DeepSeek/OpenRouter via SDK openai) — falha
                    # de plataforma, nao bug do grafo. O no llm re-levanta esses tipos (_EXCECOES_LLM,
                    # nos/llm.py) e aqui escalamos como modelo_indisponivel (bucket infra) em vez de cair no
                    # `except Exception` generico abaixo, que mataria o turno sem escalada (o ARQ NAO
                    # retenta excecao comum — so `Retry` explicito ou shutdown do worker).
                    logger.error("api_indisponivel turno_id=%s", turno_id)
                    await escalar_por_exaustao(
                        pool, atendimento["id"], turno_id, motivo="modelo_indisponivel"
                    )
                    AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    break
                except Exception:
                    # Bug generico no grafo (nao 5xx do provider, que o ramo acima ja pegou). O ARQ
                    # NAO retenta excecao comum, entao sem escalada aqui o turno morria em silencio:
                    # cliente sem resposta e ninguem avisado. Escala ANTES de re-levantar, no mesmo
                    # padrao dos ramos de exaustao — `abrir_handoff` e idempotente (nao abre segunda
                    # escalada com uma aberta), entao o retry de shutdown nao duplica card. A
                    # excecao original nunca e mascarada: se a propria escalada falhar, ela vira log
                    # e o `raise` sai igual.
                    logger.exception("graph_erro turno_id=%s", turno_id)
                    try:
                        await escalar_por_exaustao(
                            pool, atendimento["id"], turno_id, motivo="erro_interno"
                        )
                        AGENTE_TURNO_RESULTADO.labels("exaustao").inc()
                    except Exception:
                        logger.exception("escalada_erro_interno_falhou turno_id=%s", turno_id)
                    raise
                finally:
                    AGENTE_TURNO_DURACAO.labels(modelo_chat, tipo_turno).observe(
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
                    and motivo_parada(m.response_metadata) in PARADA_RECUSA
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
                    and motivo_parada(m.response_metadata) in PARADA_TRUNCADA
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
                # 7. extrai resposta + msgs do cliente do turno (read receipt, 05 §4.2).
                #    `post_process` ja zerou TUDO quando a pausa veio de fora (Pix/foto); quando ela
                #    e do PROPRIO turno (escalar) ele preserva a fala emitida ANTES do tool_call --
                #    essa bolha precisa sair, senao toda escalada vira silencio ao cliente (o
                #    descarte do pos-escalar, 04 §3.5, segue valendo).
                #
                #    MAS o `post_process` le `ia_pausada` ANTES do output_guard (que roda um judge
                #    LLM): na janela de segundos entre os dois, um pipeline externo pode pausar e o
                #    texto ja escapou do zeramento. Por isso o passo 6 rele — e aqui o descarte
                #    passa a valer para TODA pausa que este turno nao abriu, com texto ou sem. Sem
                #    isto o turno seguia despachando por cima da modelo que ja esta atendendo.
                texto = extrair_texto_do_turno(resultado["messages"])
                # 3o rastro de pausa-deste-turno: o CARIMBO do output_guard. `_bloquear`
                # (leak/AUP) escala direto no banco, sem tocar em `messages` — os dois rastros que
                # `pausa_aberta_por_este_turno` le (tool `escalar`, canned da escalada silenciosa)
                # nao existem nesse caminho, e a pausa aberta pelo PROPRIO grafo era logada como
                # `pausa_externa=True`, mandando o operador procurar um pipeline que nao pausou
                # nada (loop-massa r3, achado 6).
                escalou_neste_turno = bool(
                    resultado.get("_pausa_aberta_pelo_guard")
                ) or pausa_aberta_por_este_turno(resultado["messages"])
                pausa_externa = bool(pos["ia_pausada"]) and not escalou_neste_turno
                if (
                    pos["estado"] in ESTADOS_TERMINAIS
                    or pausa_externa
                    or (pos["ia_pausada"] and not texto)
                ):
                    logger.info(
                        "turno_descartado atendimento_id=%s pausa_externa=%s",
                        atendimento["id"],
                        pausa_externa,
                    )
                    AGENTE_TURNO_RESULTADO.labels("escalado").inc()
                    # O descarte NAO engole o turno critico: a bolha deterministica que o sistema
                    # ja prometeu (chave Pix) sai mesmo aqui — texto do modelo, nunca. Fora dos
                    # estados TERMINAIS: com o atendimento Fechado/Perdido nao ha o que anexar.
                    if pos["estado"] not in ESTADOS_TERMINAIS:
                        await _despachar_criticas_do_descarte(
                            ctx,
                            pool,
                            conversa_id=conversa_id,
                            turno_id=turno_id,
                            modelo_id=atendimento["modelo_id"],
                            atendimento_id=atendimento["id"],
                        )
                else:
                    async with pool.connection() as conn:
                        res = await conn.execute(
                            f"""
                            SELECT evolution_message_id, conteudo, created_at
                              FROM barravips.mensagens
                            {_WHERE_INBOUND_NAO_RESPONDIDO}
                               AND evolution_message_id IS NOT NULL
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
                                   payload->>'legenda'  AS legenda,
                                   -- De QUEM é a mídia ('eu' | 'parceira', ADR-0042). Viaja até
                                   -- `_enviar_midias` porque é lá que se decide NÃO carimbar
                                   -- `book_enviado_em`: foto da parceira não é o book dela.
                                   COALESCE(payload->>'de', 'eu') AS de
                              FROM barravips.tool_calls
                             WHERE turno_id = %s AND tool_name = 'enviar_midia'
                             ORDER BY call_idx
                            """,
                            (turno_id,),
                        )
                        midias: list[dict[str, Any]] = [dict(r) for r in await res.fetchall()]

                        # critico: ver `_SQL_TURNO_CRITICO` (mesmo criterio usado pelo resgate do
                        # turno descartado). O flag vai no PAYLOAD do job (05 §7), nao no Redis --
                        # TTL pode expirar antes da ultima retry com backoff.
                        res = await conn.execute(_SQL_TURNO_CRITICO, (turno_id,))
                        critico = await res.fetchone() is not None

                        # Pix de deslocamento: ver `_SQL_PIX_DO_TURNO`. So consultamos quando o
                        # turno é `critico`; a bolha e anexada após o texto da IA.
                        # Parceira (ADR-0042): o MESMO trilho da chave Pix, e pelo mesmo motivo —
                        # o telefone dela é string crítica que não pode passar pelo LLM. A tool
                        # `envolver_parceira` só registrou a intenção; o número é lido fresh aqui.
                        # `contato_anexado` só é true no modo "encaminhar"; `card_parceira` só no
                        # modo "dupla". Nunca os dois (o `modo` é único) — a leitura é do resultado
                        # persistido, não de nada que o modelo tenha escrito.
                        res = await conn.execute(
                            """
                            SELECT resultado->>'contato_anexado' = 'true' AS contato,
                                   resultado->>'card_parceira'   = 'true' AS card
                              FROM barravips.tool_calls
                             WHERE turno_id = %s AND tool_name = 'envolver_parceira'
                             LIMIT 1
                            """,
                            (turno_id,),
                        )
                        parceira_row = await res.fetchone()
                        contato_parceira: tuple[str, str] | None = None
                        if parceira_row and parceira_row.get("contato"):
                            contato_parceira = await contato_da_parceira(
                                conn, atendimento["modelo_id"]
                            )

                        pix_row: dict[str, Any] | None = None
                        if critico:
                            res = await conn.execute(
                                _SQL_PIX_DO_TURNO, (atendimento["modelo_id"], turno_id)
                            )
                            pix_row = await res.fetchone()

                    msg_ids_cliente: list[str] = [r["evolution_message_id"] for r in inbound]
                    chars_inbound = sum(len(r["conteudo"] or "") for r in inbound)
                    # inbound mais recente do turno: âncora do defer humano (05 §4.1) — o
                    # sampler desconta o que o pipeline já gastou desde a msg do cliente.
                    recebida_em = max((r["created_at"] for r in inbound), default=None)

                    chunks, quote_alvos = chunk_texto(texto)
                    # casa cada alvo de `[quote]` com (evolution_message_id, texto do balão) da
                    # mensagem do cliente alvo. `[quote: trecho]` busca a msg que contém o trecho;
                    # `[quote]` puro pega a última. Sem inbound, o alvo é ignorado (None).
                    quote_msg_ids, quote_textos = _resolver_quotes(quote_alvos, inbound)
                    # Anexa a bolha do Pix (bug F) como ÚLTIMA bolha do turno, sem quote. Quando o
                    # turno pediu Pix ele já é `critico` (não-cancelável), então a chave sempre sai.
                    if pix_row and pix_row.get("chave_pix"):
                        # Descarta a bolha-ponte de pré-anúncio ("mandando por aqui") antes da chave
                        # — redundante com a bolha determinística logo abaixo (listas de quote são
                        # paralelas aos chunks, então a última posição cai junto).
                        if chunks and _eh_pre_anuncio_pix(chunks[-1]):
                            logger.info(
                                "pix_pre_anuncio_descartado turno_id=%s bolha=%r",
                                turno_id,
                                chunks[-1],
                            )
                            chunks = chunks[:-1]
                            quote_msg_ids = quote_msg_ids[:-1]
                            quote_textos = quote_textos[:-1]
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
                    # Bolha determinística do CONTATO da parceira (fluxo A), última do turno e sem
                    # quote — igual à do Pix. O número nunca esteve no prompt nem na saída do LLM:
                    # ele nasce aqui, do cadastro. A rede anti-Pix do output_guard absolve
                    # exatamente esta forma (`eh_bolha_de_contato_da_parceira`) e continua matando
                    # chave inventada — ver `agente/_parceria.py`.
                    if contato_parceira is not None:
                        chunks = [
                            *chunks,
                            formatar_bolha_contato_parceira(*contato_parceira),
                        ]
                        quote_msg_ids = [*quote_msg_ids, None]
                        quote_textos = [*quote_textos, None]
                    # Card NÃO-BLOQUEANTE da dupla (fluxo B): a parceira pode estar `inativa` e sem
                    # disponibilidade cadastrada, e a venda NÃO espera por isso — a modelo do canal
                    # já cravou o horário. O card só PEDE ao Fernando confirmar. Best-effort, como
                    # o judge pós-envio: `_job_id` estático deduplica o replay do turno, e uma
                    # falha de enqueue não pode derrubar um turno que já foi resolvido.
                    if parceira_row and parceira_row.get("card"):
                        try:
                            await redis.enqueue_job(
                                "enviar_card",
                                tipo="parceira_a_confirmar",
                                atendimento_id=str(atendimento["id"]),
                                _job_id=f"card:parceira:{atendimento['id']}",
                            )
                        except Exception:
                            logger.exception("card_parceira_enqueue_falhou turno_id=%s", turno_id)
                    if not chunks and not midias:
                        logger.warning("turno_sem_resposta turno_id=%s", turno_id)
                        AGENTE_TURNO_RESULTADO.labels("ok_sem_resposta").inc()
                    else:
                        # NB: metricas de tokens NAO sao emitidas aqui — o no llm ja emite
                        # AGENTE_TURNO_TOKENS (M2-T2, via ephemeral_5m+1h). Reemitir duplicaria a
                        # contagem e reintroduziria o bug do cache_creation=0 (auditoria 24-05).
                        defer_envio = await despachar_humanizacao(
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
                            recebida_em=recebida_em,
                            # Isencao do gate de pausa do fire SO para o turno que abriu a PROPRIA
                            # pausa (bolha de espera pre-`escalar` / canned da escalada silenciosa).
                            # Derivado do rastro do turno, nao do bit do banco: `ia_pausada` sozinho
                            # nao distingue "eu escalei" de "a foto de portaria chegou agora" e
                            # mandava a IA falar por cima da modelo. Pausa externa nem chega aqui
                            # (descartada acima); o `and` fica como cinto-suspensorio.
                            ignorar_pausa=bool(pos["ia_pausada"]) and escalou_neste_turno,
                            # Carimbo do `<valor_dele_serve>` (prepare_context -> State): o
                            # write-time do envio o casa com a bolha despachada e grava a venda no
                            # número DELE. Lido do State, não recomputado — ver `estado.py`.
                            valor_dele_no_prompt=resultado.get("valor_dele_no_prompt"),
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
                        # Judge PÓS-ENVIO (produção assistida): 100% dos turnos com texto
                        # despachado ganham um job assíncrono de telemetria (rastro/voz/conduta).
                        # Defer curto p/ o envio humanizado terminar antes do julgamento;
                        # _job_id estático deduplica re-execuções do turno. Best-effort: o
                        # enqueue nunca derruba o turno já despachado.
                        if chunks and get_settings().judge_pos_envio_ativo:
                            try:
                                await ctx["redis"].enqueue_job(
                                    "julgar_turno_pos_envio",
                                    conversa_id=conversa_id,
                                    turno_id=turno_id,
                                    chunks=chunks,
                                    trace_id=trace_id_eval,
                                    # Corte do contexto: agora é ANTES do envio, então toda
                                    # bolha da IA daqui pra frente é deste turno. Sem ele o
                                    # judge só sabia cortar por conteúdo — e a rede final
                                    # transforma a bolha antes de persistir.
                                    desde=datetime.now(UTC).isoformat(),
                                    _job_id=f"judge_pos:{turno_id}",
                                    # acompanha o defer humano do envio: sem isso o judge
                                    # dispararia antes do fire e leria `enviados:` vazio
                                    # (nao_enviado, max_tries=1 = telemetria perdida).
                                    _defer_by=120 + defer_envio,
                                )
                            except Exception:
                                logger.warning(
                                    "judge_pos_envio enqueue falhou turno_id=%s",
                                    turno_id,
                                    exc_info=True,
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


def _turnos_deste_job(ctx: dict[str, Any]) -> set[str]:
    """Todos os `turno_id` que ESTE job pode ter emitido — um por iteracao do drain.

    O `turno_id` e deterministico por `(job_id, score, loop_idx)` (01 §6.7), entao o job retentado
    recalcula exatamente os mesmos ids. Serve p/ distinguir "outro turno pegou a janela" de "sou eu
    mesmo voltando de um crash".
    """
    return {str(uuid5(NS_TURNO, f"{ctx['job_id']}:{ctx['score']}:{i}")) for i in range(MAX_DRAIN)}


async def _fallback_tem_trabalho(
    pool: AsyncConnectionPool[Any],
    redis: Any,
    ctx: dict[str, Any],
    conv_uuid: UUID,
    conversa_id: str,
) -> bool:
    """`pending:conv` ausente — ainda assim ha turno a rodar? Quem responde e o BANCO.

    Duas checagens, nesta ordem (a barata primeiro):

    1. **Resposta em voo** — `enviar_turno` pode estar deferido (delay humano, ate
       `envio_delay_humano_teto_s`) e a bolha da IA so vira linha em `mensagens` quando dispara;
       nesse intervalo o banco ainda diria "inbound sem resposta" e responderiamos duas vezes.
       `turno_atual:{conv}` (EX=600) marca quem pegou a janela: marcador de OUTRO turno => a
       resposta e dele, nao ha o que fazer. Marcador deste job (ou ausente) => seguimos.
    2. **Ha inbound nao respondido?** — `ha_inbound_nao_respondido`, o mesmo predicado da janela
       do passo 7.

    Buraco residual conhecido e ACEITO: crash entre o `delete(pending)` e o passo 3 (que grava o
    `turno_atual`) com um marcador do turno ANTERIOR ainda vivo faz a retomada ser barrada aqui —
    janela de milissegundos no turno de texto (resolver atendimento + gates), maior so no de audio
    (BLPOP de 8s). Preferimos o silencio ao double-texting; a proxima mensagem do cliente recupera.
    """
    marcador = await redis.get(f"turno_atual:{conversa_id}")
    if isinstance(marcador, (bytes, bytearray)):
        marcador = marcador.decode("utf-8")
    if marcador is not None and marcador not in _turnos_deste_job(ctx):
        return False
    async with pool.connection() as conn:
        return await ha_inbound_nao_respondido(conn, conv_uuid)


async def ha_inbound_nao_respondido(conn: AsyncConnection[Any], conversa_id: UUID) -> bool:
    """Sobrou mensagem do cliente DEPOIS da ultima bolha da IA nesta conversa?

    Fonte de verdade do gate de pendencia quando o Redis nao tem a janela. Usa o mesmo
    `_WHERE_INBOUND_NAO_RESPONDIDO` do read receipt do passo 7 — logo, ja e o anti-double-texting:
    com a IA tendo falado por ultimo o predicado nao casa nada e o gate fecha.
    """
    res = await conn.execute(
        f"SELECT 1 FROM barravips.mensagens {_WHERE_INBOUND_NAO_RESPONDIDO} LIMIT 1",
        (conversa_id, conversa_id),
    )
    return await res.fetchone() is not None


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

    # Trilho do A/B vivo (experimento_braco): com o flag ligado, o atendimento nasce carimbado
    # num braço determinístico e sticky por cliente, computado em SQL para herdar c.cliente_id da
    # subquery sem round-trip extra na criação. DESLIGADO por default — e nesse caso a coluna nem
    # entra na query, então `resolver_atendimento` roda contra o schema pré-migration (a coluna
    # experimento_braco pode não existir em prod até a migration ser aplicada). Os fragmentos são
    # literais constantes (sem input do usuário) — nada de injeção.
    if get_settings().experimento_braco_ativo:
        col_braco = ", experimento_braco"
        sel_braco = (
            ", CASE WHEN get_byte(decode(md5(c.cliente_id::text), 'hex'), 0) % 2 = 0 "
            "THEN 'controle' ELSE 'tratamento' END"
        )
    else:
        col_braco = ""
        sel_braco = ""

    # Herda o vendedor padrão da modelo (ADR 0012): quando a IA conduz a modelo,
    # modelos.vendedor_id já é NULL → atendimento sem comissão, transição limpa.
    # `modelos.status` liga/desliga a IA (CONTEXT.md): modelo pausada/inativa faz o atendimento
    # NOVO nascer já pausado, com o mesmo motivo do POST /v1/modelos/{id}/pausar. Sem isso o
    # freio manual vazava — o endpoint só pausa os atendimentos ABERTOS na hora, e cliente novo
    # (ou recorrência depois de um terminal) voltava a ser atendido pela IA com a modelo pausada.
    res = await conn.execute(
        f"""
        INSERT INTO barravips.atendimentos
          (cliente_id, modelo_id, conversa_id, estado, fonte_decisao_ultima_transicao, vendedor_id,
           ia_pausada, ia_pausada_motivo, responsavel_atual{col_braco})
        SELECT c.cliente_id, c.modelo_id, c.id, 'Novo', 'extracao_ia', m.vendedor_id,
               m.status <> 'ativa',
               CASE WHEN m.status <> 'ativa' THEN 'modelo_pausada'::barravips.ia_pausada_motivo_enum END,
               CASE WHEN m.status <> 'ativa' THEN 'modelo' ELSE 'IA' END::barravips.responsavel_atual_enum{sel_braco}
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

    Contrato: exclui terminais (`Fechado`/`Perdido`). A ressurreicao de `rotear_imagem`
    (ADR 0027) depende disso — so age quando este devolve None (interno morto por timeout).
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
    descricao = _DESCRICAO_EXAUSTAO.get(motivo, f"encerrou por '{motivo}'")
    async with pool.connection() as conn:
        await abrir_handoff(
            conn,
            atendimento_id=atendimento_id,
            responsavel=responsavel,
            tipo=tipo,
            resumo_operacional=(
                f"Agente nao encerrou o turno: {descricao}. "
                f"turno_id={turno_id}. Verificar o trace do turno."
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
    recebida_em: datetime | None = None,
    defer_humano: bool = True,
    ignorar_pausa: bool = False,
    valor_dele_no_prompt: int | None = None,
) -> int:
    """Um unico job `enviar_turno` por turno (05 §1): percorre chunks e midias em ordem (07 §3.4).

    O job `enviar_turno` nasce no M4c; aqui so o despacho pelo NOME, com dedupe nativo via _job_id.
    Quando `envio_delay_humano_habilitado`, adia o job via _defer_by (latência humana de resposta,
    05 §4.1) descontando o que o pipeline já gastou desde `recebida_em` (inbound mais recente do
    turno). Turno CRITICO nunca adia: ele pula o cancel-on-new-message no fire, então um crítico
    deferido poderia sair DEPOIS da resposta do turno seguinte (inversão real) — e chave Pix /
    confirmação não devem esperar. Retorna o defer aplicado (s), p/ o caller alinhar o judge.

    `valor_dele_no_prompt` viaja intacto do State até o job: é o carimbo do `<valor_dele_serve>`
    (ADR-0040), e o write-time do `enviar_turno` o transforma em `valor_acordado` quando a bolha
    despachada de fato aceita o número dele. Aqui não se decide nada — só o transporte, como o
    `critico`: quem julga a bolha é quem a envia.

    `ignorar_pausa` isenta o turno do gate de pausa no fire (`enviar_turno`) — só o turno que abriu
    a própria pausa (bolha de espera pré-`escalar`) usa, e quem decide isso é
    `pausa_aberta_por_este_turno`, não o bit `ia_pausada` do banco (que não distingue a pausa deste
    turno da que um pipeline externo abriu no meio dele).
    """
    elapsed_s = (
        max(0.0, (datetime.now(UTC) - recebida_em).total_seconds())
        if recebida_em is not None
        else 0.0
    )
    defer_s = (
        0
        if critico or not defer_humano
        else amostrar_defer_humano_s(chars_inbound=chars_inbound, elapsed_s=elapsed_s)
    )
    extra: dict[str, Any] = {"_defer_by": defer_s} if defer_s > 0 else {}
    arq = ctx["redis"]  # em ARQ, ctx["redis"] e a ArqRedis e expoe enqueue_job
    job = await arq.enqueue_job(
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
        ignorar_pausa=ignorar_pausa,
        valor_dele_no_prompt=valor_dele_no_prompt,
        _job_id=f"turno_envio:{turno_id}",
        **extra,
    )
    if job is None:
        # Dedupe do retry (job `turno_envio:` já existe): o `enviar_turno` REAL ficou com o defer
        # da 1ª tentativa, que esta amostra fresca desconhece. Devolve o TETO p/ a margem do judge
        # nunca encolher; sem re-observar a métrica (o defer real já foi observado na 1ª vez).
        s = get_settings()
        return s.envio_delay_humano_teto_s if s.envio_delay_humano_habilitado else 0
    ENVIO_DEFER_HUMANO.observe(defer_s)
    return defer_s
