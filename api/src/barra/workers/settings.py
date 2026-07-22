"""ARQ WorkerSettings — registra cron jobs determinísticos.

Cron:
  - timeout_longo (24h sem cliente): a cada 5 min
  - timeout_interno (45 min sem foto portaria, contado do mais tarde entre aviso de saida e horario combinado): a cada minuto
  - cancelar_piloto_teste (cancelamento de seguranca do piloto, ADR-0033; interno: aviso de saida ou perto do horario combinado; externo/remoto: 10 min em Aguardando_confirmacao; default on): a cada minuto
  - confirmar_em_execucao (bloqueio.inicio <= now): a cada minuto
  - cobrar_valor_final (Lembrete de fechamento, ADR-0009; fim do atendimento): a cada minuto
  - reengajar_silenciosos (toque proativo apos cotacao; default off): a cada 5 min
  - limpar_midias_vencidas (90d em estados terminais): diário 03:00
  - fluxo_drift (sensor de deriva de fluxo; observacional, default off): segunda 04:00
  - rollback_watch (gatilhos objetivos de rollback do piloto; alerta dev): diário 05:00
  - digest_semanal (resumo diário pro Fernando no grupo de Coordenação): diário 12:00

Idempotência: dedupe_key = (conversa_id, turno_id, chunk_idx) consultada antes do envio.
"""

import asyncio
import logging
import sys
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings
from arq.cron import CronJob
from openai import AsyncOpenAI

from barra.agente._custo import modelos_para_langfuse
from barra.agente.graph import build_graph
from barra.core.db import criar_pool, fechar_pool
from barra.core.evolution import EvolutionClient
from barra.core.logging import setup_logging
from barra.core.storage import criar_minio
from barra.core.tracing import init_sentry, registrar_modelos_langfuse, setup_langfuse
from barra.settings import Settings, get_settings
from barra.workers.comprovante_fechamento import fechar_via_comprovante
from barra.workers.coordenador import processar_turno
from barra.workers.digest_semanal import enviar_digest_semanal
from barra.workers.envio import MAX_TRIES_ENVIO, enviar_card, enviar_turno
from barra.workers.feedback_rig import enviar_ack_feedback_rig, enviar_aviso_desenvolvido
from barra.workers.fluxo_drift import medir_fluxo_drift
from barra.workers.judge_pos_envio import julgar_turno_pos_envio
from barra.workers.lembrete_valor import cobrar_valor_final
from barra.workers.media import limpar_midias_vencidas, rotear_imagem, transcrever_audio
from barra.workers.pix import validar_pix
from barra.workers.reconciliacao import reconciliar_cards_escalada
from barra.workers.revisao_baixo_score import coletar_baixo_score
from barra.workers.rollback_watch import vigiar_gatilhos_rollback
from barra.workers.timeouts import (
    aplicar_timeout_interno,
    aplicar_timeout_longo,
    cancelar_piloto_teste,
    confirmar_em_execucao,
    reengajar_silenciosos,
)

# psycopg async no Windows (dev local) precisa do selector loop antes do loop do worker subir,
# senao PoolTimeout (09 §4.10; main.py:20 faz o mesmo). Producao e Linux. Como o startup roda
# JA dentro do loop, o guard tem que ficar no import do modulo.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger(__name__)


async def cron_timeout_longo(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await aplicar_timeout_longo(conn)


async def cron_timeout_interno(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await aplicar_timeout_interno(conn)


async def cron_confirmar_em_execucao(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await confirmar_em_execucao(conn)


async def cron_cobrar_valor_final(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    evolution = ctx.get("evolution")
    settings = ctx.get("settings")
    if pool is None or evolution is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await cobrar_valor_final(conn, evolution, settings)


async def cron_reengajar(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    redis = ctx.get("redis")
    settings = ctx.get("settings")
    if pool is None or redis is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await reengajar_silenciosos(conn, redis, settings)


async def cron_cancelar_piloto(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    redis = ctx.get("redis")
    settings = ctx.get("settings")
    if pool is None or redis is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await cancelar_piloto_teste(conn, redis, settings)


async def cron_limpar_midias(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    minio = ctx.get("minio")
    if pool is None:
        return 0
    async with pool.connection() as conn:
        return await limpar_midias_vencidas(conn, minio)


async def cron_reconciliar_cards(ctx: dict[str, Any]) -> int:
    # Rede de segurança contra handoff silencioso: entrega cards de escalada órfãos chamando
    # enviar_card inline (ctx tem db_pool + evolution). Ver workers/reconciliacao.py.
    return await reconciliar_cards_escalada(ctx)


async def cron_fluxo_drift(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    settings = ctx.get("settings")
    if pool is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await medir_fluxo_drift(conn, settings)


async def cron_baixo_score(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    settings = ctx.get("settings")
    if pool is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await coletar_baixo_score(conn, settings)


async def cron_digest_semanal(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    evolution = ctx.get("evolution")
    settings = ctx.get("settings")
    if pool is None or evolution is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await enviar_digest_semanal(conn, evolution, settings)


async def cron_rollback_watch(ctx: dict[str, Any]) -> int:
    pool = ctx.get("db_pool")
    settings = ctx.get("settings")
    if pool is None or settings is None:
        return 0
    async with pool.connection() as conn:
        return await vigiar_gatilhos_rollback(conn, settings)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    # Logging estruturado JSON no nivel log_level — primeiro, p/ os logs subsequentes do
    # startup (e o INFO do coordenador) saírem em vez de cair no WARNING default do root.
    setup_logging(settings)
    # O agente roda aqui (worker), entao Sentry e tracing tem de subir aqui. Sentry captura a
    # excecao do turno (integracao arq) com a tag turno_id (OBS-04); sem DSN e no-op.
    init_sentry(settings)
    # tracing Langfuse self-hosted (ADR 0019) — trace legível, PII na infra própria (sem masking);
    # o coordenador anexa o handler global aos callbacks do graph.ainvoke. No-op sem chaves. O grafo
    # roda AQUI (worker), então é aqui que as generations nascem: registra os modelos p/ o Langfuse
    # precificar o total_cost (senão fica 0) e nomeia o service.name do trace.
    setup_langfuse(settings, servico="barra-worker")
    registrar_modelos_langfuse(modelos_para_langfuse())
    # Expoe as metricas do worker (agente_turno_*, agente_custo_turno_brl) p/ scrape em :9091.
    # Guard por ambiente: nao sobe em teste (a suite reusa o processo e a porta colidiria).
    if settings.ambiente != "teste":
        from prometheus_client import start_http_server

        # best-effort (igual ao vision_client=None abaixo): metricas nunca podem impedir o worker
        # de subir — ex.: :9091 ja ocupada por outro worker no mesmo host/netns.
        try:
            start_http_server(9091)
        except OSError:
            logger.warning("metrics_http_server_falhou", exc_info=True)
    # max_size=20/autocommit=True para o turno (07 §2). NAO criar ctx["redis"]: o ARQ ja injeta
    # a ArqRedis em ctx["redis"] antes do startup — sobrescrever mataria enqueue_job.
    ctx["db_pool"] = await criar_pool(settings.database_url, max_size=20, autocommit=True)
    ctx["minio"] = criar_minio(settings)
    ctx["evolution"] = EvolutionClient(settings)
    ctx["graph"] = build_graph()  # SEM checkpointer no P0 (01 §6.7)
    # Cliente de vision para validar_pix (06 §0 item 4 + §2.3): OpenAI-compatível apontado para
    # OpenRouter; instanciado uma vez e reutilizado entre invocações. Sem chave configurada,
    # mantemos None — o openai SDK rejeita api_key vazia no construtor e derrubaria o worker;
    # validar_pix lida com vision_client=None levantando ao ser chamado (nao deveria sem chave).
    # timeout 60s + 3 retries (espelha o openai_client abaixo, REL-04): vision pendurado nao pode
    # segurar o slot do worker ate o job_timeout=400s.
    if settings.openrouter_api_key:
        ctx["vision_client"] = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=60.0,
            max_retries=3,
        )
    else:
        ctx["vision_client"] = None
    # Cliente OpenAI compartilhado entre invocacoes de transcrever_audio (06 §1.3): timeout 60s
    # + 3 retries automaticos no SDK; 5xx persistente sobe como APIError e o ARQ retenta o job.
    if settings.openai_api_key:
        ctx["openai_client"] = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=60.0, max_retries=3
        )
    else:
        ctx["openai_client"] = None
    # Re-arma os gauges de rollback (barra_rollback_gatilho) no boot. Eles vivem no processo, e
    # todo deploy de prompt força update deste worker: sem isto a série SOME e o alerta que estava
    # firing "resolve" sozinho — silêncio indistinguível de "voltou ao normal" até o cron das 05:00.
    # Best-effort: falha aqui (DB frio) não pode derrubar o boot; o cron reavalia depois.
    if settings.ambiente != "teste" and settings.rollback_watch_ativo:
        try:
            async with ctx["db_pool"].connection() as conn:
                await vigiar_gatilhos_rollback(conn, settings)
        except Exception:
            logger.warning("rollback_watch_boot_falhou", exc_info=True)


async def shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("db_pool")
    if pool is not None:
        await fechar_pool(pool)
    vision_client = ctx.get("vision_client")
    if vision_client is not None:
        await vision_client.close()


def _redis_settings(settings: Settings) -> RedisSettings:
    if settings.redis_url:
        return RedisSettings.from_dsn(settings.redis_url)
    return RedisSettings()


_settings = get_settings()


class WorkerSettings:
    """Configuração ARQ. Usar: `arq barra.workers.settings.WorkerSettings`."""

    redis_settings = _redis_settings(_settings)
    on_startup = startup
    on_shutdown = shutdown
    # keep_result=0 SO p/ processar_turno (09 §4.9): o keep_result=3600 global quebra o
    # re-enqueue do drain (_job_id estatico) por 1h apos o termino (arq#416/#432).
    functions: ClassVar[list[Any]] = [
        # max_tries=2: turno caro — erro transitorio pos-LLM NAO deve reinvocar o Sonnet 5x (REL-03).
        func(processar_turno, keep_result=0, max_tries=2),
        # MAX_TRIES_ENVIO nos envios (REL-03): retry de rede Evolution; keep_result default (global
        # 3600). Constante importada de envio.py — o dead-end de envio crítico usa o MESMO valor.
        func(enviar_card, max_tries=MAX_TRIES_ENVIO),  # cards no grupo (05 §6)
        func(enviar_turno, max_tries=MAX_TRIES_ENVIO),  # humanização do turno (05 §1/§4)
        func(rotear_imagem),  # roteamento de imagem sob lock:conv (06 §2.1)
        func(validar_pix),  # validação de comprovante (06 §2.2); keep_result default
        # Auto-fechamento por comprovante de Pix no grupo (auto-baixa). max_tries=1: o OCR não
        # re-queima crédito de LLM em retry (erros de vision já são capturados e viram "sem valor";
        # o fechamento em si é idempotente pelo guard de estado do _registrar_fechado).
        func(fechar_via_comprovante, max_tries=1),
        # STT do agente (06 §1.3): fire-and-forget; sinalizacao via canal Redis (06 §1.4), nao
        # via keep_result. Mas keep_result global=3600 + _job_id estatico (transcricao:{evolution_message_id})
        # nao bloqueia retry — o evolution_message_id e unico por audio, entao nao ha re-enqueue.
        func(transcrever_audio),
        # Judge PÓS-ENVIO (produção assistida): telemetria de 100% dos turnos enviados.
        # max_tries=1: telemetria não re-queima crédito de LLM em falha (o turno fica sem
        # julgamento e a métrica `indisponivel` registra).
        # max_tries=2 serve SÓ ao Retry explícito do ramo pré-LLM (marcador de envio ainda
        # ausente): zero crédito re-queimado, e o `ja_julgado` barra duplicata depois do LLM.
        func(julgar_turno_pos_envio, max_tries=2),
        # Ack de registro do rig de feedback (deferido ~2 min, coalesce por grupo). max_tries=1:
        # sinalização best-effort, não re-tenta.
        func(enviar_ack_feedback_rig, max_tries=1),
        # Aviso de "desenvolvido" (fecho de issue via webhook GitHub). max_tries=1: idem.
        func(enviar_aviso_desenvolvido, max_tries=1),
    ]
    cron_jobs: ClassVar[list[CronJob]] = [
        cron(cron_timeout_interno, name="timeout_interno"),
        # Janela de disparo estreita (10min fixos, ADR-0033) -> a cada minuto, mesmo padrao do
        # timeout_interno.
        cron(cron_cancelar_piloto, name="cancelar_piloto_teste"),
        cron(cron_confirmar_em_execucao, name="confirmar_em_execucao"),
        cron(cron_cobrar_valor_final, name="cobrar_valor_final"),
        cron(
            cron_timeout_longo,
            name="timeout_longo",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(
            cron_reengajar,
            name="reengajar_silenciosos",
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        cron(cron_limpar_midias, name="limpar_midias", hour={3}, minute={0}),
        cron(cron_reconciliar_cards, name="reconciliar_cards"),
        # Sensor de deriva de fluxo (observacional, flag default OFF): segunda 04:00 UTC, fora de pico.
        cron(cron_fluxo_drift, name="fluxo_drift", weekday="mon", hour={4}, minute={0}),
        # Coletor de turnos reprovados → dataset de regressão (observacional, flag OFF): diário 04:30.
        cron(cron_baixo_score, name="baixo_score", hour={4}, minute={30}),
        # Vigia dos gatilhos de rollback do piloto (janela 7d, alerta dev): diário 05:00 UTC.
        cron(cron_rollback_watch, name="rollback_watch", hour={5}, minute={0}),
        # Digest diário pro Fernando no grupo de Coordenação: diário 12:00 UTC (09:00 BRT).
        cron(cron_digest_semanal, name="digest_semanal", hour={12}, minute={0}),
    ]
    keep_result = 3600  # global; processar_turno sobrescreve p/ 0 via func(...) acima
    max_jobs = 10
    job_timeout = 400  # so a rede externa: cobre MAX_DRAIN x (60s graph + overhead) (07 §2)
