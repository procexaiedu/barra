"""Job de envio Evolution com registro em envios_evolution."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import timedelta
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from barra.core.errors import ErroDominio
from barra.core.evolution import EvolutionClient
from barra.core.metrics import ENVIO_DURACAO, ENVIO_RESULTADO, ENVIO_RETRIES
from barra.dominio.escaladas.modelos import TipoEscalada, rotulo_tipo_escalada
from barra.workers._cards import render_card

logger = logging.getLogger(__name__)


async def enviar_texto_job(
    conn: AsyncConnection[Any],
    client: EvolutionClient,
    *,
    instance_id: str,
    remote_jid: str,
    texto: str,
    contexto: str,
    tipo: str,
    payload: dict[str, Any] | None = None,
) -> str:
    if not instance_id:
        raise ErroDominio("EVOLUTION_NAO_PAREADA", "Evolution nao pareada.", status_code=409)
    return await client.enviar_texto(
        conn=conn,
        instance_id=instance_id,
        remote_jid=remote_jid,
        texto=texto,
        contexto=contexto,
        tipo=tipo,
        payload=payload or {},
    )


# --- Cards no grupo de Coordenação (05 §6) ----------------------------------
# Cards são jobs ARQ diretos, enviados pelo EvolutionClient SEM passar pela humanização.
# Uma função `enviar_card` única despacha por `tipo`; cada renderer é idempotente por owner
# (06 §9): só envia se o card ainda não foi enviado e grava o id no próprio dono.


async def _card_escalada(ctx: dict[str, Any], *, escalada_id: str, **_: Any) -> None:
    """Card de handoff no grupo de Coordenação (05 §6).

    Idempotência por owner: só envia se `escaladas.card_message_id IS NULL`. O POST
    (→ envios_evolution, via `enviar_texto`) e a gravação do `card_message_id` vivem na
    MESMA transação — o retry do ARQ relê a coluna e não reenvia.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.tipo::text AS tipo, e.resumo_operacional, e.acao_esperada,
                   e.card_message_id, a.numero_curto, cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
             WHERE e.id = %s
            """,
            (UUID(escalada_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        rotulo = rotulo_tipo_escalada(TipoEscalada(e["tipo"])) if e["tipo"] else "Handoff"
        texto = render_card(
            "escalada",
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            tipo_rotulo=rotulo,
            resumo_operacional=e["resumo_operacional"],
            acao_esperada=e["acao_esperada"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=e["evolution_instance_id"],
                remote_jid=e["coordenacao_chat_id"],
                texto=texto,
                contexto="coordenacao",
                tipo="card_escalada",
            )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, UUID(escalada_id)),
            )


async def _card_pix(
    ctx: dict[str, Any],
    *,
    atendimento_id: str,
    comprovante_id: str,
    **_: Any,
) -> None:
    """Card "saída confirmada" no grupo de Coordenação (06 §2.5).

    `tipo='pix_validado'` e `tipo='pix_em_revisao'` partilham o mesmo renderer: o atendimento
    ja esta `Confirmado` em ambos (Pix nunca trava, 01 §6.1); o template diferencia pela
    presenca de `motivo_em_revisao` (sinaliza a duvidez para a modelo decidir antes de pedir
    o Uber). Idempotência por owner: so envia se `comprovantes_pix.card_message_id IS NULL`.
    """
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT cp.card_message_id,
                   cp.decisao_pipeline::text AS decisao_pipeline,
                   cp.motivo_em_revisao,
                   cp.valor_extraido,
                   a.numero_curto, a.endereco, a.valor_acordado,
                   b.inicio AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.comprovantes_pix cp
              JOIN barravips.atendimentos a ON a.id = cp.atendimento_id
              JOIN barravips.modelos      mo ON mo.id = a.modelo_id
              JOIN barravips.clientes     cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE cp.id = %s
            """,
            (UUID(comprovante_id),),
        )
        cp = await res.fetchone()
        if not cp or cp["card_message_id"]:
            return  # idempotência por owner: card já enviado

        texto = render_card(
            "pix",
            numero_curto=cp["numero_curto"],
            cliente_nome=cp["cliente_nome"] or "cliente",
            endereco=cp["endereco"],
            horario=cp["bloqueio_inicio"],
            valor_acordado=cp["valor_acordado"],
            valor_extraido=cp["valor_extraido"],
            decisao=cp["decisao_pipeline"],
            motivo_em_revisao=cp["motivo_em_revisao"],
        )
        async with conn.transaction():
            mid = await evolution.enviar_texto(
                conn=conn,
                instance_id=cp["evolution_instance_id"],
                remote_jid=cp["coordenacao_chat_id"],
                texto=texto,
                contexto="coordenacao",
                tipo="card_pix",
            )
            await conn.execute(
                "UPDATE barravips.comprovantes_pix SET card_message_id = %s WHERE id = %s",
                (mid, UUID(comprovante_id)),
            )
    del atendimento_id  # vem no payload do job p/ _job_id; renderer le tudo do comprovante


async def _card_chegada(
    ctx: dict[str, Any], *, atendimento_id: str, **_: Any
) -> None:
    """Card "cliente chegou" no grupo de Coordenação (06 §4).

    Anexa a foto de portaria do cliente (presigned URL do MinIO, TTL 30min) — a
    modelo precisa conferir antes de abrir a porta (CONTEXT.md "Foto de portaria").
    Idempotência por owner: `handoff_foto_portaria_ia` ja criou uma escalada
    tipo='foto_portaria' responsavel='modelo' para hospedar o `card_message_id`;
    o renderer le a foto da mensagem mais recente tipo='imagem' do atendimento
    (a entrada que disparou o handoff, gravada pelo webhook). POST + UPDATE
    na MESMA transacao (espelha _card_escalada/_card_pix).
    """
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution: EvolutionClient = ctx["evolution"]

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT e.id AS escalada_id, e.card_message_id,
                   a.numero_curto, a.endereco,
                   b.inicio AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id,
                   foto.media_object_key AS foto_object_key
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.modelos      mo ON mo.id = a.modelo_id
              JOIN barravips.clientes     cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
              LEFT JOIN LATERAL (
                  SELECT media_object_key
                    FROM barravips.mensagens
                   WHERE conversa_id = a.conversa_id
                     AND tipo = 'imagem'
                     AND direcao = 'cliente'
                     AND media_object_key IS NOT NULL
                   ORDER BY created_at DESC
                   LIMIT 1
              ) foto ON true
             WHERE e.atendimento_id = %s AND e.tipo = 'foto_portaria'
             ORDER BY e.created_at DESC
             LIMIT 1
            """,
            (UUID(atendimento_id),),
        )
        e = await res.fetchone()
        if not e or e["card_message_id"]:
            return  # idempotência por owner: card já enviado

        texto = render_card(
            "chegada",
            numero_curto=e["numero_curto"],
            cliente_nome=e["cliente_nome"] or "cliente",
            endereco=e["endereco"],
            horario=e["bloqueio_inicio"],
        )

        url = minio.presigned_get_object(
            ctx["settings"].minio_bucket_media,
            e["foto_object_key"],
            expires=timedelta(minutes=30),
        ) if e["foto_object_key"] else None

        async with conn.transaction():
            if url:
                mid = await evolution.enviar_midia(
                    conn=conn,
                    instance_id=e["evolution_instance_id"],
                    remote_jid=e["coordenacao_chat_id"],
                    url=url,
                    caption=texto,
                    media_type="foto",
                    contexto="coordenacao",
                    tipo="card_chegada",
                )
            else:
                # Defesa: foto nao foi gravada (caso raro); manda so o texto para a modelo
                # nao perder o card "cliente chegou".
                mid = await evolution.enviar_texto(
                    conn=conn,
                    instance_id=e["evolution_instance_id"],
                    remote_jid=e["coordenacao_chat_id"],
                    texto=texto,
                    contexto="coordenacao",
                    tipo="card_chegada",
                )
            await conn.execute(
                "UPDATE barravips.escaladas SET card_message_id = %s WHERE id = %s",
                (mid, e["escalada_id"]),
            )


async def _card_aviso_saida(
    ctx: dict[str, Any], *, atendimento_id: str, **_: Any
) -> None:
    """Card "cliente saiu de casa" no grupo de Coordenação (06 §5).

    Sem owner (aviso_saida nao tem escalada — emenda §0 item 8): idempotencia por
    SETNX `card:aviso_saida:{atendimento_id}` com TTL 24h. Se a key ja existe,
    retorna sem enviar (replay do ARQ ou segundo "to indo" do mesmo cliente).
    """
    pool = ctx["db_pool"]
    redis = ctx["redis"]
    evolution: EvolutionClient = ctx["evolution"]

    chave = f"card:aviso_saida:{atendimento_id}"
    if not await redis.set(chave, "1", ex=86400, nx=True):
        return  # ja enviado: replay/segundo aviso do mesmo cliente

    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT a.numero_curto,
                   b.inicio AS bloqueio_inicio,
                   cl.nome AS cliente_nome,
                   mo.coordenacao_chat_id, mo.evolution_instance_id
              FROM barravips.atendimentos a
              JOIN barravips.modelos  mo ON mo.id = a.modelo_id
              JOIN barravips.clientes cl ON cl.id = a.cliente_id
              LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
             WHERE a.id = %s
            """,
            (UUID(atendimento_id),),
        )
        a = await res.fetchone()
        if not a:
            return

        texto = render_card(
            "aviso_saida",
            numero_curto=a["numero_curto"],
            cliente_nome=a["cliente_nome"] or "cliente",
            horario=a["bloqueio_inicio"],
        )
        await evolution.enviar_texto(
            conn=conn,
            instance_id=a["evolution_instance_id"],
            remote_jid=a["coordenacao_chat_id"],
            texto=texto,
            contexto="coordenacao",
            tipo="card_aviso_saida",
        )


async def _card_loc_pin(ctx: dict[str, Any], **_: Any) -> None:
    # TODO(M3d): pin de localização do endereço, enfileirado após `registrar_extracao` (09 §4.3).
    raise NotImplementedError("card de pin de localização será preenchido no M3d")


_RENDER_CARD: dict[str, Callable[..., Awaitable[None]]] = {
    "escalada": _card_escalada,
    "pix_validado": _card_pix,
    "pix_em_revisao": _card_pix,
    "chegada": _card_chegada,
    "aviso_saida": _card_aviso_saida,
    "loc_pin": _card_loc_pin,
}


async def enviar_card(ctx: dict[str, Any], *, tipo: str, **kw: Any) -> None:
    """Job ARQ: envia um card no grupo de Coordenação direto pelo Evolution, sem passar pela
    humanização (05 §6). Dispatch por `tipo`; cada renderer é idempotente por owner."""
    render = _RENDER_CARD[tipo]
    await render(ctx, **kw)


# --- Humanização: job único `enviar_turno` por turno (05 §1/§4) --------------
# Read receipt + reading delay, chunks de texto e depois mídias, EM ORDEM, com cancel-on-
# new-message (turno não-crítico) e dedupe mark-after-send. Um único job percorre o turno em
# laço — jobs por chunk rodariam concorrentes (`max_jobs`) e não garantiriam ordem (05 §1).


def calcular_typing_ms(_texto: str) -> int:
    """Typing 0.8-2.0s, plano (05 §4.1). O que vende humanização é o 'digitando…' aparecer,
    não a duração exata, então random plano em vez de proporcional ao tamanho."""
    return random.randint(800, 2000)  # noqa: S311 -- jitter de humanização, nao cripto


def calcular_pausa_ms() -> int:
    """Pausa entre chunks: 400-1200ms uniform (05 §4.1)."""
    return random.randint(400, 1200)  # noqa: S311 -- jitter de humanização, nao cripto


def calcular_reading_delay_ms(chars_inbound: int) -> int:
    """Reading delay antes do PRIMEIRO 'composing' (humano lê → digita → responde), proporcional
    ao inbound do turno com piso e teto enxutos (05 §4.1)."""
    return min(500 + chars_inbound * 12, 3000)


def _redis_eq(valor: object, esperado: str) -> bool:
    """Compara um valor lido do Redis com uma str. A ArqRedis injetada em `ctx['redis']` não usa
    `decode_responses`, então `get` devolve bytes — decodifica antes (igual a core/redis.py:59)."""
    if valor is None:
        return False
    if isinstance(valor, bytes):
        valor = valor.decode()
    return valor == esperado


async def _carregar_destino(pool: AsyncConnectionPool[Any], conversa_id: str) -> dict[str, Any]:
    """Destino do envio: instância da modelo, chat do cliente e o atendimento aberto da conversa.
    `evolution_instance_id` vive em `modelos`; `evolution_chat_id` em `conversas`."""
    async with pool.connection() as conn:
        res = await conn.execute(
            """
            SELECT mo.evolution_instance_id AS evolution_instance_id,
                   c.evolution_chat_id      AS evolution_chat_id,
                   a.id                      AS atendimento_id
              FROM barravips.conversas c
              JOIN barravips.modelos mo ON mo.id = c.modelo_id
              LEFT JOIN LATERAL (
                  SELECT id
                    FROM barravips.atendimentos
                   WHERE conversa_id = c.id AND estado NOT IN ('Fechado', 'Perdido')
                   ORDER BY created_at DESC
                   LIMIT 1
              ) a ON true
             WHERE c.id = %s
            """,
            (UUID(conversa_id),),
        )
        row = await res.fetchone()
    if row is None:
        raise ErroDominio("CONVERSA_NAO_ENCONTRADA", "Conversa nao encontrada.", status_code=404)
    return cast(dict[str, Any], row)


async def enviar_turno(
    ctx: dict[str, Any],
    *,
    conversa_id: str,
    turno_id: str,
    chunks: list[str],
    midias: list[dict[str, Any]],
    msg_ids_cliente: list[str],
    chars_inbound: int,
    critico: bool = False,
) -> None:
    """Envia um turno chunk-by-chunk e depois as mídias (05 §4).

    `critico` vem no PAYLOAD do job (não do Redis, cujo TTL pode expirar antes da última retry
    com backoff): turno crítico (write tool com efeito) entrega tudo ignorando o cancel; falha
    final do job + crítico → `escalar_por_exaustao` (05 §7).
    """
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    evolution: EvolutionClient = ctx["evolution"]

    if ctx.get("job_try", 1) > 1:
        ENVIO_RETRIES.inc()

    inicio = perf_counter()
    conv: dict[str, Any] | None = None
    try:
        conv = await _carregar_destino(pool, conversa_id)
        conversa_uuid = UUID(conversa_id)

        # 0. read receipt + reading delay (lê antes de digitar, 05 §4.2). O membro "read" do set
        #    evita re-dormir o delay no retry; markAsRead em si já é idempotente. Roda ANTES do
        #    cancel: marcar lido é inócuo mesmo que o turno seja cancelado em seguida.
        if msg_ids_cliente and not await redis.sismember(f"enviados:{turno_id}", "read"):
            await evolution.marcar_lida(
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                message_ids=msg_ids_cliente,
            )
            await asyncio.sleep(calcular_reading_delay_ms(chars_inbound) / 1000)
            await redis.sadd(f"enviados:{turno_id}", "read")
            await redis.expire(f"enviados:{turno_id}", 600)

        for idx, conteudo in enumerate(chunks):
            # 1. cancel-on-new-message (turno crítico ignora o check, 05 §3)
            if not critico and not _redis_eq(
                await redis.get(f"turno_atual:{conversa_id}"), turno_id
            ):
                logger.info("turno_cancelado turno_id=%s idx=%s", turno_id, idx)
                ENVIO_RESULTADO.labels("cancelado").inc()
                return
            # 2. dedupe: retry do job re-percorre desde idx 0 e pula o que já entregou (05 §4.3)
            if await redis.sismember(f"enviados:{turno_id}", f"chunk:{idx}"):
                continue

            # 3. presence composing
            typing_ms = calcular_typing_ms(conteudo)
            await evolution.set_presence(
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                presence="composing",
                delay_ms=typing_ms,
            )
            await asyncio.sleep(typing_ms / 1000)

            # 4 + 5. POST (→ envios_evolution) e persistência em mensagens, na MESMA transação
            async with pool.connection() as conn, conn.transaction():
                mid = await evolution.enviar_texto(
                    conn=conn,
                    instance_id=conv["evolution_instance_id"],
                    remote_jid=conv["evolution_chat_id"],
                    texto=conteudo,
                    contexto="conversa_cliente",
                    tipo="texto",
                    atendimento_id=conv["atendimento_id"],
                    conversa_id=conversa_uuid,
                )
                await conn.execute(
                    """
                    INSERT INTO barravips.mensagens
                      (conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
                    VALUES (%s, %s, 'ia', 'texto', %s, %s)
                    ON CONFLICT (evolution_message_id) DO NOTHING
                    """,
                    (conversa_uuid, conv["atendimento_id"], conteudo, mid),
                )

            # 6. MARK-AFTER-SEND: só agora idx conta como entregue (05 §4.3)
            await redis.sadd(f"enviados:{turno_id}", f"chunk:{idx}")
            await redis.expire(f"enviados:{turno_id}", 600)

            # 7. jitter
            await asyncio.sleep(calcular_pausa_ms() / 1000)

        if await _enviar_midias(ctx, conversa_id, turno_id, midias, conv, critico):
            ENVIO_RESULTADO.labels("ok").inc()
    except Exception:
        # Falha final do job (ARQ não vai retentar): job_try chegou ao teto de tentativas.
        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 5)
        if job_try >= max_tries:
            logger.exception("envio_falha_final turno_id=%s critico=%s", turno_id, critico)
            if critico and conv is not None:
                # Dead-end (05 §7): efeito já no banco, mensagem pode não ter chegado → escala.
                from barra.workers.coordenador import escalar_por_exaustao

                await escalar_por_exaustao(
                    pool, conv["atendimento_id"], turno_id, motivo="envio_exaurido_critico"
                )
                ENVIO_RESULTADO.labels("exaustao_critico").inc()
            else:
                ENVIO_RESULTADO.labels("falha_evolution").inc()
        raise
    finally:
        ENVIO_DURACAO.observe(perf_counter() - inicio)


async def _enviar_midias(
    ctx: dict[str, Any],
    conversa_id: str,
    turno_id: str,
    midias: list[dict[str, Any]],
    conv: dict[str, Any],
    critico: bool,
) -> bool:
    """Fase de mídia do MESMO job, depois de todos os chunks de texto (05 §5). A ordem é sempre
    texto→mídia; a legenda de cada mídia carrega o contexto dela. Devolve `False` se cancelou no
    meio (não conta como envio 'ok')."""
    redis = ctx["redis"]
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    evolution: EvolutionClient = ctx["evolution"]
    conversa_uuid = UUID(conversa_id)

    for idx, item in enumerate(midias):
        if not critico and not _redis_eq(await redis.get(f"turno_atual:{conversa_id}"), turno_id):
            logger.info("turno_cancelado_midia turno_id=%s idx=%s", turno_id, idx)
            ENVIO_RESULTADO.labels("cancelado").inc()
            return False
        if await redis.sismember(f"enviados:{turno_id}", f"midia:{idx}"):
            continue

        async with pool.connection() as conn:
            res = await conn.execute(
                "SELECT tipo, bucket, object_key FROM barravips.modelo_midia WHERE id = %s",
                (item["midia_id"],),
            )
            m = await res.fetchone()
        if not m:
            logger.error("midia_nao_encontrada midia_id=%s", item["midia_id"])
            continue

        # presence "recording" para vídeo, "composing" para foto
        presence = "recording" if m["tipo"] == "video" else "composing"
        await evolution.set_presence(
            instance_id=conv["evolution_instance_id"],
            remote_jid=conv["evolution_chat_id"],
            presence=presence,
            delay_ms=1500,
        )
        await asyncio.sleep(1.5)

        # URL assinada regenerada NO job (TTL 30min) — nunca cachear no payload: os retries do
        # ARQ (backoff exponencial) podem ocorrer >5min depois (05 §5).
        url = minio.presigned_get_object(
            m["bucket"], m["object_key"], expires=timedelta(minutes=30)
        )
        async with pool.connection() as conn, conn.transaction():
            mid = await evolution.enviar_midia(
                conn=conn,
                instance_id=conv["evolution_instance_id"],
                remote_jid=conv["evolution_chat_id"],
                url=url,
                caption=item.get("legenda") or None,
                media_type=m["tipo"],
                contexto="conversa_cliente",
                tipo=m["tipo"],
                # view-once p/ vídeo (Mídia exclusiva, 01 §6.13): efetivo só quando a Evolution
                # self-host expuser o campo no sendMedia; ignorado até lá.
                view_once=(m["tipo"] == "video"),
                atendimento_id=conv["atendimento_id"],
                conversa_id=conversa_uuid,
            )
            await conn.execute(
                """
                INSERT INTO barravips.mensagens
                  (conversa_id, atendimento_id, direcao, tipo, conteudo,
                   media_object_key, evolution_message_id)
                VALUES (%s, %s, 'ia', %s, %s, %s, %s)
                ON CONFLICT (evolution_message_id) DO NOTHING
                """,
                (
                    conversa_uuid,
                    conv["atendimento_id"],
                    m["tipo"],
                    item.get("legenda") or "",
                    m["object_key"],
                    mid,
                ),
            )

        await redis.sadd(f"enviados:{turno_id}", f"midia:{idx}")
        await redis.expire(f"enviados:{turno_id}", 600)
        await asyncio.sleep(0.6)
    return True
