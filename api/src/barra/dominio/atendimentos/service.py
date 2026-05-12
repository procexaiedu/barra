"""Orquestracao do ciclo de vida de um atendimento aberto por par (cliente, modelo)."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

Origem = Literal["webhook", "painel_fernando"]


@dataclass(frozen=True)
class Atendimento:
    id: UUID
    numero_curto: int
    estado: str
    cliente_id: UUID
    modelo_id: UUID
    conversa_id: UUID
    ja_existia: bool


async def garantir_atendimento_aberto(
    conn: AsyncConnection[Any],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    origem: Origem,
    evolution_chat_id: str | None = None,
) -> Atendimento:
    """Garante exatamente um atendimento aberto no par (cliente_id, modelo_id).

    Faz upsert da conversa do par e devolve o atendimento aberto existente,
    criando um novo apenas quando nao existe. `origem` registra quem disparou
    a criacao (webhook ingerindo mensagem vs. POST manual no painel).
    """
    del origem  # mantido na assinatura para auditoria futura, sem uso atual.
    if evolution_chat_id is None:
        conversa = await _one(
            conn,
            """
            INSERT INTO barravips.conversas (cliente_id, modelo_id)
            VALUES (%s, %s)
            ON CONFLICT (cliente_id, modelo_id)
            DO UPDATE SET cliente_id = EXCLUDED.cliente_id
            RETURNING id
            """,
            (cliente_id, modelo_id),
        )
    else:
        conversa = await _one(
            conn,
            """
            INSERT INTO barravips.conversas (cliente_id, modelo_id, evolution_chat_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (cliente_id, modelo_id)
            DO UPDATE SET evolution_chat_id = EXCLUDED.evolution_chat_id
            RETURNING id
            """,
            (cliente_id, modelo_id, evolution_chat_id),
        )
    assert conversa is not None

    existente = await _one(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado, cliente_id, modelo_id, conversa_id
          FROM barravips.atendimentos
         WHERE cliente_id = %s AND modelo_id = %s
           AND estado NOT IN ('Fechado', 'Perdido')
        """,
        (cliente_id, modelo_id),
    )
    if existente is not None:
        return Atendimento(
            id=existente["id"],
            numero_curto=existente["numero_curto"],
            estado=existente["estado"],
            cliente_id=existente["cliente_id"],
            modelo_id=existente["modelo_id"],
            conversa_id=existente["conversa_id"],
            ja_existia=True,
        )

    novo = await _one(
        conn,
        """
        INSERT INTO barravips.atendimentos (cliente_id, modelo_id, conversa_id)
        VALUES (%s, %s, %s)
        RETURNING id, numero_curto, estado::text AS estado, cliente_id, modelo_id, conversa_id
        """,
        (cliente_id, modelo_id, conversa["id"]),
    )
    assert novo is not None
    return Atendimento(
        id=novo["id"],
        numero_curto=novo["numero_curto"],
        estado=novo["estado"],
        cliente_id=novo["cliente_id"],
        modelo_id=novo["modelo_id"],
        conversa_id=novo["conversa_id"],
        ja_existia=False,
    )


async def _one(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()
