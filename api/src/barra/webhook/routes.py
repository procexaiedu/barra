import asyncio
import io
import logging
from typing import Any, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, Request

from barra.core.errors import ErroDominio, JidNaoPermitido
from barra.core.evolution import envio_existe
from barra.core.metrics import COMANDOS_GRUPO, WEBHOOK_ERRORS
from barra.dominio.atendimentos.service import garantir_conversa
from barra.dominio.escaladas.service import Autor, aplicar_comando
from barra.webhook.despacho import enfileirar_turno
from barra.webhook.parser import MensagemEvolution, extrair_mensagem, parse_comando_grupo

router = APIRouter()

_logger = logging.getLogger(__name__)

_MIME_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}


async def _baixar_midia(url: str) -> tuple[bytes, str] | None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
        ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        return resp.content, ct
    except Exception as exc:
        _logger.warning("falha_download_midia url=%s erro=%s", url, exc)
        return None


async def _upload_minio(minio: Any, bucket: str, key: str, data: bytes, content_type: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: minio.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type),
    )


@router.post("/evolution")
async def evolution_webhook(
    request: Request,
    x_webhook_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    settings = request.app.state.settings
    provided = x_webhook_token or (authorization.removeprefix("Bearer ").strip() if authorization else None)
    if settings.evolution_webhook_token and provided != settings.evolution_webhook_token:
        WEBHOOK_ERRORS.labels("auth").inc()
        raise ErroDominio("WEBHOOK_NAO_AUTORIZADO", "Webhook nao autorizado.", status_code=401)

    payload = await request.json()

    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco indisponivel.", status_code=503)

    evento = _evento_normalizado(payload)
    if evento in {"connection.update", "qrcode.updated", "application.startup"}:
        async with pool.connection() as conn:
            return await _processar_evento_instancia(conn, payload, evento)

    msg = extrair_mensagem(payload)
    if msg is None:
        return {"status": "ignored"}
    if settings.jid_permitido and msg.remote_jid != settings.jid_permitido:
        raise JidNaoPermitido()

    minio = getattr(request.app.state, "minio", None)

    # Baixar mídia antes de abrir conexão, para não segurar o pool durante I/O de rede.
    midia: tuple[bytes, str] | None = None
    if msg.tipo != "texto" and msg.media_url and minio is not None:
        midia = await _baixar_midia(msg.media_url)

    async with pool.connection() as conn:
        if await _mensagem_ja_persistida(conn, msg.evolution_message_id):
            return {"status": "duplicate"}
        if settings.evolution_grupo_coordenacao_jid and msg.remote_jid == settings.evolution_grupo_coordenacao_jid:
            return await _processar_grupo(conn, request, msg)
        # Defesa em profundidade para mensagens de cliente: a instance precisa
        # estar cadastrada em barravips.modelos.evolution_instance_id, já que
        # o desenho do produto é 'uma instância Evolution por modelo'. Grupos
        # de coordenação usam a instance da modelo dona do grupo e já têm
        # filtragem própria por JID.
        if not await _instance_cadastrada(conn, msg.instance_id):
            WEBHOOK_ERRORS.labels("instance").inc()
            _logger.warning(
                "webhook_instance_desconhecida instance=%s remote=%s",
                msg.instance_id,
                msg.remote_jid,
            )
            return {"status": "unknown_instance"}
        conversa_id = await _persistir_cliente(conn, msg, minio, settings.minio_bucket_media, midia)

    # Webhook fino (01 §4.1 / 06 §0.1): a mensagem foi persistida orfa (atendimento_id=NULL);
    # quem resolve/cria o atendimento e roda o turno e o coordenador. So enfileira.
    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        if msg.tipo == "texto":
            await enfileirar_turno(arq, conversa_id, msg.evolution_message_id)
        elif msg.tipo == "imagem":
            # 06 §2.1: nao roteia sincronamente — rotear_imagem decide sob lock:conv.
            await arq.enqueue_job(
                "rotear_imagem",
                mensagem_id=msg.evolution_message_id,
                conversa_id=str(conversa_id),
                media_url=msg.media_url,
                caption=msg.caption,
                _job_id=f"rotear:{msg.evolution_message_id}",
            )
        else:
            # TODO(M5a): enqueue transcrever_audio (06 §1)
            pass
    return {"status": "received"}


def _evento_normalizado(payload: dict[str, Any]) -> str | None:
    """Normaliza CONNECTION_UPDATE/connection.update etc para a forma com
    pontos em minúsculas."""
    raw = payload.get("event")
    if not isinstance(raw, str) or not raw:
        return None
    return raw.replace("_", ".").lower()


def _extrair_state(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        state = data.get("state")
        if isinstance(state, str):
            return state
    return None


def _extrair_instance_id(payload: dict[str, Any]) -> str | None:
    for chave in ("instance", "instanceName"):
        valor = payload.get(chave)
        if isinstance(valor, str) and valor:
            return valor
    data = payload.get("data")
    if isinstance(data, dict):
        for chave in ("instance", "instanceName"):
            valor = data.get(chave)
            if isinstance(valor, str) and valor:
                return valor
    return None


async def _processar_evento_instancia(
    conn: Any, payload: dict[str, Any], evento: str | None
) -> dict[str, str]:
    instance_id = _extrair_instance_id(payload)
    if not instance_id:
        return {"status": "ignored"}

    if evento == "qrcode.updated":
        # QR já é entregue ao painel via REST (POST /conectar-whatsapp).
        # Este evento serve apenas para auditoria leve.
        _logger.info("evolution_qrcode_updated instance=%s", instance_id)
        return {"status": "qrcode_logged"}

    if evento == "application.startup":
        _logger.info("evolution_application_startup instance=%s", instance_id)
        return {"status": "startup_logged"}

    # evento == 'connection.update'
    state = _extrair_state(payload)
    if state == "open":
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'conectado',
                   evolution_pareado_em = now()
             WHERE evolution_instance_id = %s
            """,
            (instance_id,),
        )
        return {"status": "connection_open"}
    if state == "close":
        # Não zeramos evolution_instance_id — apenas marcamos desconectado.
        # Limpeza completa só acontece em /desparear-whatsapp.
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'desconectado'
             WHERE evolution_instance_id = %s
            """,
            (instance_id,),
        )
        return {"status": "connection_close"}
    if state == "connecting":
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = 'pareando'
             WHERE evolution_instance_id = %s
               AND evolution_status <> 'conectado'
            """,
            (instance_id,),
        )
        return {"status": "connection_connecting"}
    return {"status": "ignored"}


async def _instance_cadastrada(conn: Any, instance_id: str | None) -> bool:
    if not instance_id:
        return False
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.modelos WHERE evolution_instance_id = %s LIMIT 1",
        (instance_id,),
    )
    return row is not None


async def _processar_grupo(conn: Any, request: Request, msg: MensagemEvolution) -> dict[str, str]:
    settings = request.app.state.settings
    if await envio_existe(conn, msg.evolution_message_id):
        return {"status": "outbound_ignored"}
    autor = _autor_grupo(settings.evolution_fernando_jids, msg)
    if autor is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        return {"status": "ignored"}

    quoted_numero: int | None = None
    aguardando_valor = False
    if msg.quoted_message_id:
        quoted_numero, aguardando_valor = await _resolver_card(conn, msg.quoted_message_id)
    comando = parse_comando_grupo(msg.texto, quoted_numero, aguardando_valor=aguardando_valor)
    if comando is None:
        return {"status": "ignored"}
    atendimento_id = None
    if comando.numero_curto is not None:
        atendimento_id = await _atendimento_por_numero(conn, comando.numero_curto)
    if atendimento_id is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        return {"status": "invalid"}
    await aplicar_comando(
        conn,
        origem="grupo_coordenacao",
        autor=autor,
        atendimento_id=atendimento_id,
        comando=comando.comando,
        payload=comando.payload | {"texto": msg.texto, "evolution_message_id": msg.evolution_message_id},
    )
    COMANDOS_GRUPO.labels("valido" if comando.erro is None else "invalido").inc()
    return {"status": "processed" if comando.erro is None else "invalid"}


async def _persistir_cliente(
    conn: Any,
    msg: MensagemEvolution,
    minio: Any,
    bucket: str,
    midia: tuple[bytes, str] | None,
) -> UUID:
    """Persiste a mensagem do cliente como orfa (atendimento_id=NULL) e devolve o conversa_id.

    Webhook fino (06 §0.1): faz upsert apenas da CONVERSA do par; quem resolve/cria o
    atendimento e cobre as orfas e o coordenador (`processar_turno`), sob `lock:conv`.
    """
    async with conn.transaction():
        modelo = await _one(
            conn,
            "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
            (msg.instance_id,),
        )
        if modelo is None:
            raise ErroDominio("MODELO_NAO_RESOLVIDA", "Modelo nao resolvida.", status_code=404)
        telefone = msg.remote_jid.split("@", 1)[0]
        cliente = await _one(
            conn,
            """
            INSERT INTO barravips.clientes (telefone, primeiro_contato_modelo_id)
            VALUES (%s, %s)
            ON CONFLICT (telefone) DO UPDATE SET telefone = EXCLUDED.telefone
            RETURNING *
            """,
            (telefone, modelo["id"]),
        )
        assert cliente is not None
        conversa_id = await garantir_conversa(
            conn,
            cliente_id=cliente["id"],
            modelo_id=modelo["id"],
            evolution_chat_id=msg.remote_jid,
        )

        # Fazer upload da mídia para MinIO e obter a key permanente. Sem atendimento, a key
        # deriva da conversa (06 §0.1 #2). Se falhar, gravar como tipo='texto' p/ satisfazer
        # a constraint de DB.
        media_key: str | None = None
        tipo_db = msg.tipo
        if msg.tipo != "texto" and midia is not None and minio is not None:
            data, ct = midia
            ext = _MIME_EXT.get(ct, ".jpg" if msg.tipo == "imagem" else ".ogg")
            key = f"conversas/{conversa_id}/mensagens/{msg.evolution_message_id}{ext}"
            try:
                await _upload_minio(minio, bucket, key, data, ct or "application/octet-stream")
                media_key = key
            except Exception as exc:
                _logger.warning("falha_upload_minio key=%s erro=%s", key, exc)

        # Constraint: tipo != 'texto' requer media_object_key NOT NULL.
        if msg.tipo != "texto" and media_key is None:
            tipo_db = "texto"
            _logger.warning(
                "midia_sem_upload_salva_como_texto evolution_id=%s tipo_original=%s",
                msg.evolution_message_id,
                msg.tipo,
            )

        # atendimento_id=NULL: orfa intencional, coberta depois pelo coordenador (07 §3.2).
        await conn.execute(
            """
            INSERT INTO barravips.mensagens (
              conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id
            )
            VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (
                conversa_id,
                None,
                tipo_db,
                msg.texto,
                media_key,
                msg.evolution_message_id,
            ),
        )
    return conversa_id


async def _mensagem_ja_persistida(conn: Any, evolution_message_id: str) -> bool:
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.mensagens WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    return row is not None


async def _resolver_card(conn: Any, card_message_id: str) -> tuple[int | None, bool]:
    """Resolve um card citado -> (numero_curto, é_card_de_Lembrete_de_fechamento).

    Olha primeiro `envios_evolution` (cobre o card do Lembrete de fechamento e qualquer outbound
    backend ligado a atendimento; ADR-0009); cai para `escaladas.card_message_id` (handoffs)."""
    row = await _one(
        conn,
        """
        SELECT a.numero_curto, (e.payload->>'card_kind' = 'lembrete_valor') AS lembrete
          FROM barravips.envios_evolution e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
         WHERE e.evolution_message_id = %s
        """,
        (card_message_id,),
    )
    if row is not None:
        return row["numero_curto"], bool(row["lembrete"])
    return await _numero_por_card(conn, card_message_id), False


async def _numero_por_card(conn: Any, card_message_id: str | None) -> int | None:
    if not card_message_id:
        return None
    row = await _one(
        conn,
        """
        SELECT a.numero_curto
          FROM barravips.escaladas e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
         WHERE e.card_message_id = %s
        """,
        (card_message_id,),
    )
    return row["numero_curto"] if row else None


async def _atendimento_por_numero(conn: Any, numero_curto: int) -> Any | None:
    # TODO(P1, multi-modelo): numero_curto e UNIQUE por (modelo_id, numero_curto), nao global.
    # Resolver modelo_id via msg.instance_id e filtrar aqui antes de ativar a 2a modelo.
    row = await _one(
        conn,
        """
        SELECT id FROM barravips.atendimentos
         WHERE numero_curto = %s AND estado NOT IN ('Fechado', 'Perdido')
         ORDER BY updated_at DESC
         LIMIT 1
        """,
        (numero_curto,),
    )
    return row["id"] if row else None


async def _one(conn: Any, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return cast(dict[str, Any] | None, await result.fetchone())


def _autor_grupo(fernando_jids: list[str], msg: MensagemEvolution) -> Autor | None:
    if msg.sender_jid and msg.sender_jid in fernando_jids:
        return "Fernando"
    if msg.from_me:
        return "modelo"
    return None
