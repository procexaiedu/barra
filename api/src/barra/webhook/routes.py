from typing import Any, cast

from fastapi import APIRouter, Header, Request

from barra.core.errors import ErroDominio, JidNaoPermitido
from barra.core.evolution import envio_existe
from barra.core.metrics import COMANDOS_GRUPO, WEBHOOK_ERRORS
from barra.dominio.escaladas.service import Autor, aplicar_comando
from barra.webhook.parser import MensagemEvolution, extrair_mensagem, parse_comando_grupo

router = APIRouter()


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
    msg = extrair_mensagem(payload)
    if msg is None:
        return {"status": "ignored"}
    if settings.jid_permitido and msg.remote_jid != settings.jid_permitido:
        raise JidNaoPermitido()
    if settings.evolution_instancia and msg.instance_id and msg.instance_id != settings.evolution_instancia:
        WEBHOOK_ERRORS.labels("instance").inc()
        raise ErroDominio("INSTANCE_NAO_PERMITIDA", "Instance nao permitida.", status_code=403)

    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise ErroDominio("BANCO_INDISPONIVEL", "Banco indisponivel.", status_code=503)

    async with pool.connection() as conn:
        if await _mensagem_ja_persistida(conn, msg.evolution_message_id):
            return {"status": "duplicate"}
        if settings.evolution_grupo_coordenacao_jid and msg.remote_jid == settings.evolution_grupo_coordenacao_jid:
            return await _processar_grupo(conn, request, msg)
        await _persistir_cliente(conn, msg)
    return {"status": "received"}


async def _processar_grupo(conn: Any, request: Request, msg: MensagemEvolution) -> dict[str, str]:
    settings = request.app.state.settings
    if await envio_existe(conn, msg.evolution_message_id):
        return {"status": "outbound_ignored"}
    autor = _autor_grupo(settings.evolution_fernando_jids, msg)
    if autor is None:
        COMANDOS_GRUPO.labels("invalido").inc()
        return {"status": "ignored"}

    quoted_numero = await _numero_por_card(conn, msg.quoted_message_id) if msg.quoted_message_id else None
    comando = parse_comando_grupo(msg.texto, quoted_numero)
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


async def _persistir_cliente(conn: Any, msg: MensagemEvolution) -> None:
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
        conversa = await _one(
            conn,
            """
            INSERT INTO barravips.conversas (cliente_id, modelo_id, evolution_chat_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (cliente_id, modelo_id)
            DO UPDATE SET evolution_chat_id = EXCLUDED.evolution_chat_id
            RETURNING *
            """,
            (cliente["id"], modelo["id"], msg.remote_jid),
        )
        assert conversa is not None
        atendimento = await _one(
            conn,
            """
            SELECT * FROM barravips.atendimentos
             WHERE cliente_id = %s AND modelo_id = %s AND estado NOT IN ('Fechado', 'Perdido')
            """,
            (cliente["id"], modelo["id"]),
        )
        if atendimento is None:
            atendimento = await _one(
                conn,
                """
                INSERT INTO barravips.atendimentos (cliente_id, modelo_id, conversa_id)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (cliente["id"], modelo["id"], conversa["id"]),
            )
        assert atendimento is not None
        await conn.execute(
            """
            INSERT INTO barravips.mensagens (
              conversa_id, atendimento_id, direcao, tipo, conteudo, media_object_key, evolution_message_id
            )
            VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
            ON CONFLICT (evolution_message_id) DO NOTHING
            """,
            (
                conversa["id"],
                atendimento["id"],
                msg.tipo,
                msg.texto,
                msg.media_url,
                msg.evolution_message_id,
            ),
        )


async def _mensagem_ja_persistida(conn: Any, evolution_message_id: str) -> bool:
    row = await _one(
        conn,
        "SELECT 1 FROM barravips.mensagens WHERE evolution_message_id = %s",
        (evolution_message_id,),
    )
    return row is not None


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
