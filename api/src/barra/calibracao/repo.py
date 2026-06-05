"""SQL puro (psycopg3) da rotulagem de calibracao. Sempre parametrizado (ADR-0002)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.calibracao.falas import Fala


async def nome_existe(conn: AsyncConnection[Any], nome: str) -> bool:
    result = await conn.execute(
        "SELECT 1 FROM barravips.calibracao_rodadas WHERE nome = %s", (nome,)
    )
    return await result.fetchone() is not None


async def criar_rodada(
    conn: AsyncConnection[Any], nome: str, descricao: str | None, falas: list[Fala]
) -> UUID:
    """Cria a rodada e materializa suas falas na MESMA transacao."""
    result = await conn.execute(
        """
        INSERT INTO barravips.calibracao_rodadas (nome, descricao)
        VALUES (%s, %s) RETURNING id
        """,
        (nome, descricao),
    )
    row = await result.fetchone()
    assert row is not None
    rodada_id = UUID(str(row["id"]))

    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO barravips.calibracao_falas
                (rodada_id, fala_id, conversa_id, cenario, texto_resposta, historico, ordem)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            [
                (
                    rodada_id,
                    f.fala_id,
                    f.conversa_id,
                    f.cenario,
                    f.texto_resposta,
                    json.dumps(f.historico, ensure_ascii=False),
                    f.ordem,
                )
                for f in falas
            ],
        )
    return rodada_id


async def listar_rodadas(conn: AsyncConnection[Any]) -> list[dict[str, Any]]:
    result = await conn.execute(
        """
        SELECT r.id, r.nome, r.created_at, count(f.id) AS total_falas
          FROM barravips.calibracao_rodadas r
          LEFT JOIN barravips.calibracao_falas f ON f.rodada_id = r.id
         GROUP BY r.id, r.nome, r.created_at
         ORDER BY r.created_at DESC
        """
    )
    return await result.fetchall()


async def obter_rodada(conn: AsyncConnection[Any], rodada_id: UUID) -> dict[str, Any] | None:
    result = await conn.execute(
        """
        SELECT r.id, r.nome, r.created_at, count(f.id) AS total_falas
          FROM barravips.calibracao_rodadas r
          LEFT JOIN barravips.calibracao_falas f ON f.rodada_id = r.id
         WHERE r.id = %s
         GROUP BY r.id, r.nome, r.created_at
        """,
        (rodada_id,),
    )
    return await result.fetchone()


async def falas_da_rodada(
    conn: AsyncConnection[Any], rodada_id: UUID, rotulador: str
) -> list[dict[str, Any]]:
    """Falas + o rotulo DO PROPRIO rotulador (LEFT JOIN filtrado) — nunca o do outro."""
    result = await conn.execute(
        """
        SELECT f.id, f.fala_id, f.conversa_id, f.cenario, f.texto_resposta, f.historico,
               ro.passou AS meu_passou, ro.observacao AS minha_obs
          FROM barravips.calibracao_falas f
          LEFT JOIN barravips.calibracao_rotulos ro
                 ON ro.fala_pk = f.id AND ro.rotulador = %s
         WHERE f.rodada_id = %s
         ORDER BY f.ordem
        """,
        (rotulador, rodada_id),
    )
    return await result.fetchall()


async def upsert_rotulo(
    conn: AsyncConnection[Any],
    fala_pk: UUID,
    rotulador: str,
    passou: bool,
    observacao: str | None,
) -> bool:
    """Idempotente. Retorna False se a fala nao existe (FK) — caller traduz p/ 404."""
    existe = await conn.execute(
        "SELECT 1 FROM barravips.calibracao_falas WHERE id = %s", (fala_pk,)
    )
    if await existe.fetchone() is None:
        return False
    await conn.execute(
        """
        INSERT INTO barravips.calibracao_rotulos (fala_pk, rotulador, passou, observacao)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (fala_pk, rotulador)
        DO UPDATE SET passou = EXCLUDED.passou, observacao = EXCLUDED.observacao
        """,
        (fala_pk, rotulador, passou, observacao),
    )
    return True


async def rotulos_para_export(conn: AsyncConnection[Any], rodada_id: UUID) -> list[dict[str, Any]]:
    """Todos os rotulos da rodada (ambos rotuladores), por `fala_id` — usado so no export."""
    result = await conn.execute(
        """
        SELECT f.fala_id, ro.rotulador, ro.passou, ro.observacao
          FROM barravips.calibracao_rotulos ro
          JOIN barravips.calibracao_falas f ON f.id = ro.fala_pk
         WHERE f.rodada_id = %s
        """,
        (rodada_id,),
    )
    return await result.fetchall()


async def falas_para_export(conn: AsyncConnection[Any], rodada_id: UUID) -> list[dict[str, Any]]:
    result = await conn.execute(
        """
        SELECT fala_id, conversa_id, cenario, texto_resposta, historico
          FROM barravips.calibracao_falas
         WHERE rodada_id = %s
         ORDER BY ordem
        """,
        (rodada_id,),
    )
    return await result.fetchall()
