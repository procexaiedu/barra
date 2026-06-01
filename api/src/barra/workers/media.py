"""Pipelines de midia (06 §1, §2).

- `limpar_midias_vencidas`: cron diario que apaga objetos MinIO de atendimentos terminais (>90d).
- `transcrever_audio`: STT via OpenAI Whisper (06 §1.3). Le o objeto MinIO (gravado pelo webhook
  fino), transcreve, faz UPDATE em `mensagens.conteudo` e sinaliza o canal Redis
  `transcricao:{conversa_id}` para o coordenador acordar do BLPOP (06 §1.4).
- `rotear_imagem`: decide o destino de uma imagem entrante sob `lock:conv` (06 §2.1) — Pix,
  foto-portaria (handoff implicito), turno com legenda ou silencio.
"""

import asyncio
import io
import json
import logging
from datetime import timedelta
from time import perf_counter
from typing import Any
from uuid import UUID

from openai import APIError, AsyncOpenAI
from psycopg import AsyncConnection

from barra.core.metrics import (
    JOBS,
    ROTEAR_IMAGEM_DECISAO,
    TRANSCRICAO_DURACAO,
    TRANSCRICAO_RESULTADO,
)
from barra.core.redis import LockBusy, adquirir_lock
from barra.workers.coordenador import resolver_atendimento_existente

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


# Falhas na fase de download/Whisper que valem retry do ARQ. Esgotado o retry, grava placeholder
# em mensagens.conteudo (06 §1.5) — o `_falha_definitiva` chama-se a partir do `except` final.
_AUDIO_PLACEHOLDER = "[audio que nao consegui ouvir]"


async def limpar_midias_vencidas(
    conn: AsyncConnection[Any],
    minio: Minio | None,
    *,
    bucket: str = "media",
) -> int:
    result = await conn.execute(
        """
        SELECT msg.media_object_key
          FROM barravips.mensagens msg
          JOIN barravips.atendimentos a ON a.id = msg.atendimento_id
         WHERE msg.media_object_key IS NOT NULL
           AND a.estado IN ('Fechado', 'Perdido')
           AND a.updated_at < now() - interval '90 days'
        """
    )
    rows = await result.fetchall()
    apagados = 0
    if minio is not None:
        for row in rows:
            minio.remove_object(bucket, row["media_object_key"])
            apagados += 1
    else:
        apagados = len(rows)
    JOBS.labels("limpeza_midia", "sucesso").inc()
    return apagados


async def rotear_imagem(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    conversa_id: str,
    media_url: str | None = None,
    caption: str | None = None,
) -> None:
    """Decide o destino de uma imagem entrante sob `lock:conv` (06 §2.1).

    O webhook so persiste e enfileira; aqui adquirimos o lock para serializar com `processar_turno`
    e ler o estado consistente. Despacha entre validar_pix, foto-portaria (handoff implicito),
    turno (legenda dispara texto) ou silencio (imagem pura fora-fluxo: IA e cega).

    `LockBusy` (turno de texto em voo): re-enfileira a si mesmo com defer curto — midia nao e
    latency-critical e o turno solta o lock em segundos.
    """
    redis = ctx["redis"]
    pool = ctx["db_pool"]

    try:
        async with adquirir_lock(redis, f"lock:conv:{conversa_id}", ttl=60, heartbeat_interval=15):
            async with pool.connection() as conn:
                atendimento = await resolver_atendimento_existente(conn, UUID(conversa_id))

            estado = atendimento["estado"] if atendimento else None
            pix_status = atendimento["pix_status"] if atendimento else None
            tipo_atendimento = atendimento["tipo_atendimento"] if atendimento else None

            if estado == "Aguardando_confirmacao" and pix_status == "aguardando":
                assert atendimento is not None  # estado != None implica atendimento
                # `validar_pix` tem assinatura enxuta (06 §0 item 2: a midia ja esta no MinIO,
                # a URL da Evolution expira) e NAO aceita media_url — passa-lo aqui quebraria o
                # job com TypeError no ARQ real.
                await redis.enqueue_job(
                    "validar_pix",
                    mensagem_id=mensagem_id,
                    atendimento_id=str(atendimento["id"]),
                    _job_id=f"pix:{atendimento['id']}:{mensagem_id}",
                )
                ROTEAR_IMAGEM_DECISAO.labels("pix").inc()
                return

            if estado == "Aguardando_confirmacao" and tipo_atendimento == "interno":
                assert atendimento is not None
                await _handoff_foto_portaria(
                    ctx,
                    conversa_id=conversa_id,
                    atendimento_id=str(atendimento["id"]),
                    mensagem_id=mensagem_id,
                )
                ROTEAR_IMAGEM_DECISAO.labels("foto_portaria").inc()
                return

            if caption:
                # Imagem fora-fluxo COM legenda: dispara turno (IA cega responde a legenda; 06 §3).
                # Import tardio evita ciclo workers.media -> webhook.despacho -> webhook.parser.
                from barra.webhook.despacho import enfileirar_turno

                await enfileirar_turno(redis, UUID(conversa_id), mensagem_id)
                ROTEAR_IMAGEM_DECISAO.labels("fora_fluxo_legenda").inc()
                return

            # Imagem pura fora-fluxo: IA fica calada (06 §3).
            ROTEAR_IMAGEM_DECISAO.labels("silencio").inc()

    except LockBusy:
        await redis.enqueue_job(
            "rotear_imagem",
            mensagem_id=mensagem_id,
            conversa_id=conversa_id,
            media_url=media_url,
            caption=caption,
            _defer_by=timedelta(seconds=3),
        )
        ROTEAR_IMAGEM_DECISAO.labels("lock_busy").inc()


async def _handoff_foto_portaria(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    atendimento_id: str,
    mensagem_id: str,
) -> None:
    """Handoff implicito da foto de portaria (06 §4).

    Le `media_object_key` da mensagem entrante (usado pelo card 'chegada' para
    anexar a imagem), delega o SQL atomico (UPDATE atendimento + bloqueio +
    escalada owner + evento) a `dominio/atendimentos/service.py`, e enfileira
    o card. Idempotencia do card: `_job_id=card:chegada:{atendimento_id}`
    (SETNX nativo do ARQ); o renderer reverifica `escaladas.card_message_id`
    antes de POSTar (06 §9).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]

    async with pool.connection() as conn:
        res = await conn.execute(
            "SELECT media_object_key FROM barravips.mensagens WHERE id = %s",
            (UUID(mensagem_id),),
        )
        row = await res.fetchone()
        media_object_key = row["media_object_key"] if row else None

        from barra.dominio.atendimentos.service import handoff_foto_portaria_ia

        await handoff_foto_portaria_ia(
            conn,
            atendimento_id=UUID(atendimento_id),
            mensagem_id=UUID(mensagem_id),
            media_object_key=media_object_key,
        )

    await redis.enqueue_job(
        "enviar_card",
        tipo="chegada",
        atendimento_id=atendimento_id,
        _job_id=f"card:chegada:{atendimento_id}",
    )
    del conversa_id  # reservado para futuro logging; assinatura espelha o stub original


async def transcrever_audio(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    evolution_message_id: str,
) -> None:
    """Transcreve um audio do cliente via OpenAI Whisper (06 §1.3).

    Pre-requisitos: a mensagem `tipo='audio'` ja foi persistida pelo webhook fino, com
    `media_object_key` apontando para um objeto OGG no MinIO (`conversas/{conversa_id}/...`).
    Esse job NAO baixa novamente da Evolution (a URL expira; 06 §0 item 2) — le do MinIO.

    Fim do job:
      - sucesso -> UPDATE `mensagens.conteudo` com a transcricao + nota; LPUSH no canal
        `transcricao:{conversa_id}` com `{"ok": true, "mensagem_id": ...}` (EXPIRE 30s).
      - falha -> deixa o ARQ retentar (APIError 5xx, rede). Esgotado, `_falha_definitiva` grava
        o placeholder e sinaliza `{"ok": false}` para o coordenador responder canned (06 §1.4).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    minio = ctx.get("minio")
    settings = ctx["settings"]
    openai_client: AsyncOpenAI | None = ctx.get("openai_client")

    inicio = perf_counter()

    # 1. carrega o objeto de midia e a conversa.
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT conversa_id, media_object_key
              FROM barravips.mensagens
             WHERE id = %s
            """,
            (mensagem_id,),
        )
        row = await res.fetchone()
    if row is None or row["media_object_key"] is None:
        logger.warning("transcricao_sem_objeto mensagem_id=%s", mensagem_id)
        TRANSCRICAO_RESULTADO.labels("sem_audio").inc()
        await _sinalizar_canal(
            redis, str(row["conversa_id"]) if row else None, mensagem_id, ok=False
        )
        return

    conversa_id = str(row["conversa_id"])
    object_key = row["media_object_key"]

    if minio is None or openai_client is None or not settings.openai_api_key:
        # ambiente sem provider configurado: assina falha definitiva, sem retry (06 §1.5).
        logger.error(
            "transcricao_sem_provider mensagem_id=%s minio=%s openai=%s",
            mensagem_id,
            minio is not None,
            openai_client is not None,
        )
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        await _falha_definitiva(pool, redis, mensagem_id=mensagem_id, conversa_id=conversa_id)
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        return

    # 2. baixa o audio do MinIO. minio-py e sync; rode num executor pra nao bloquear o loop.
    try:
        audio_bytes = await asyncio.to_thread(
            _baixar_minio, minio, settings.minio_bucket_media, object_key
        )
    except Exception:
        logger.exception("transcricao_minio_erro mensagem_id=%s key=%s", mensagem_id, object_key)
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        # Retry ARQ; se esgotar, on_job_end NAO existe -> a logica de "esgotou" cai no caller
        # via try/except dele. Aqui re-lanca.
        raise

    # 3. chama Whisper. O cliente foi criado com timeout=60 + max_retries=3 no startup; estouros
    #    finais (APIError 5xx persistente) sobem como excecao e o ARQ retenta o job inteiro.
    try:
        resposta = await openai_client.audio.transcriptions.create(
            file=("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
            model=settings.openai_model_audio_transcribe,
            language="pt",
            response_format="verbose_json",  # whisper-1 inclui .duration aqui (06 §1.3)
        )
    except APIError:
        logger.exception("transcricao_provider_erro mensagem_id=%s", mensagem_id)
        TRANSCRICAO_RESULTADO.labels("erro_provider").inc()
        TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
        raise

    texto = (resposta.text or "").strip()
    duracao_audio = float(getattr(resposta, "duration", 0.0) or 0.0)
    nota = f"\n_(originalmente audio, {round(duracao_audio)}s)_"

    # 4. UPDATE conteudo + sinaliza canal.
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE barravips.mensagens SET conteudo = %s WHERE id = %s",
            (texto + nota, mensagem_id),
        )

    await _sinalizar_canal(redis, conversa_id, mensagem_id, ok=True)
    TRANSCRICAO_RESULTADO.labels("ok").inc()
    TRANSCRICAO_DURACAO.observe(perf_counter() - inicio)
    logger.info(
        "transcricao_ok mensagem_id=%s duracao_audio=%.1fs duracao_job=%.2fs",
        mensagem_id,
        duracao_audio,
        perf_counter() - inicio,
    )


def _baixar_minio(minio: Minio, bucket: str, object_key: str) -> bytes:
    """Le um objeto MinIO inteiro em memoria. Audios de WhatsApp sao curtos (<1MB tipico)."""
    resp = minio.get_object(bucket, object_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


async def _sinalizar_canal(
    redis: Any, conversa_id: str | None, mensagem_id: str, *, ok: bool
) -> None:
    """LPUSH + EXPIRE 30s no canal `transcricao:{conversa_id}` (06 §1.4).

    Sem conversa_id (mensagem nao encontrada), nao ha como acordar coordenador; logamos e
    saimos — esse caminho so existe defensivamente.
    """
    if not conversa_id:
        return
    chave = f"transcricao:{conversa_id}"
    await redis.lpush(chave, json.dumps({"mensagem_id": mensagem_id, "ok": ok}))
    await redis.expire(chave, 30)


async def _falha_definitiva(pool: Any, redis: Any, *, mensagem_id: str, conversa_id: str) -> None:
    """Grava placeholder em `mensagens.conteudo` e sinaliza `{"ok": false}` (06 §1.5).

    Chamado quando nao ha provider configurado (ambiente sem chave/cliente) ou no retry esgotado
    do ARQ. O canal entrega `ok=false` -> coordenador (06 §1.4) responde canned sem invocar LLM.
    """
    # Guard p/ nao sobrescrever transcricao que ja chegou via path feliz; webhook persiste
    # audio com conteudo='' (parser.py:41), entao incluir string vazia na guard.
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE barravips.mensagens
               SET conteudo = %s
             WHERE id = %s AND (conteudo IS NULL OR conteudo = '')
            """,
            (_AUDIO_PLACEHOLDER, mensagem_id),
        )
    await _sinalizar_canal(redis, conversa_id, mensagem_id, ok=False)


# Re-exporta pra o teste poder forcar o caminho de falha definitiva sem mockar AsyncOpenAI.
async def marcar_audio_falho(
    pool: Any, redis: Any, *, mensagem_id: UUID | str, conversa_id: UUID | str
) -> None:
    """Wrapper publico de _falha_definitiva (06 §1.5)."""
    await _falha_definitiva(pool, redis, mensagem_id=str(mensagem_id), conversa_id=str(conversa_id))
