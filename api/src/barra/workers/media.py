"""Workers de midia: limpeza de objetos vencidos + roteamento de imagem sob lock (06 §2)."""

import logging
from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.metrics import JOBS, ROTEAR_IMAGEM_DECISAO
from barra.core.redis import LockBusy, adquirir_lock
from barra.workers.coordenador import resolver_atendimento_existente

try:
    from minio import Minio
except ModuleNotFoundError:  # pragma: no cover
    Minio = object  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


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
                await redis.enqueue_job(
                    "validar_pix",
                    mensagem_id=mensagem_id,
                    atendimento_id=str(atendimento["id"]),
                    media_url=media_url,
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
    """Stub do handoff implicito de foto de portaria (M5d, 06 §4).

    M5d implementa: UPDATE atomico (estado=Em_execucao, ia_pausada=true,
    ia_pausada_motivo=modelo_em_atendimento, responsavel_atual=modelo, foto_portaria_em=now,
    fonte_decisao=webhook_imagem) + bloqueio em_atendimento + evento transicao_estado +
    enqueue_job("enviar_card", tipo="chegada", _job_id=f"card:chegada:{atendimento_id}").
    """
    raise NotImplementedError(
        "TODO(M5d): handoff implicito da foto de portaria (06 §4); "
        f"conversa_id={conversa_id} atendimento_id={atendimento_id} mensagem_id={mensagem_id}"
    )
