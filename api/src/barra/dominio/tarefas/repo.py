"""SQL puro psycopg3 do Módulo de Tarefas (ADR 0017 / 0002).

Ator (criador/responsável) é polimórfico `(tipo, id)` sem FK. A resolução do
nome é feita na leitura por LEFT JOIN condicional por tipo. `usuario`/`modelo`/
`vendedor` (ADR 0012) são resolvidos no `_SELECT_BASE` e ofertados no `UNION ALL`
de `listar_responsaveis`.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.dominio.tarefas.schemas import (
    AtorRef,
    PrazoFiltro,
    ResponsavelOpcao,
    TarefaResponse,
)

# Hoje em BRT: prazo é `date` (sem tz); comparar com o "hoje" de São Paulo evita
# o off-by-one de meia-noite que já mordeu o painel (mesma defesa do financeiro).
_HOJE_BRT = "(now() AT TIME ZONE 'America/Sao_Paulo')::date"

_SELECT_BASE = """
    SELECT
      t.id, t.titulo, t.descricao,
      t.status::text   AS status,
      t.prioridade::text AS prioridade,
      t.prazo,
      t.criado_por_tipo::text AS criado_por_tipo,
      t.criado_por_id,
      t.atribuido_tipo::text  AS atribuido_tipo,
      t.atribuido_id,
      t.concluida_em, t.created_at, t.updated_at,
      CASE t.criado_por_tipo
        WHEN 'usuario'  THEN cu.nome
        WHEN 'modelo'   THEN cm.nome
        WHEN 'vendedor' THEN cv.nome
      END AS criado_por_nome,
      CASE t.atribuido_tipo
        WHEN 'usuario'  THEN au.nome
        WHEN 'modelo'   THEN am.nome
        WHEN 'vendedor' THEN av.nome
      END AS atribuido_nome
      FROM barravips.tarefas t
      LEFT JOIN barravips.usuarios   cu ON t.criado_por_tipo = 'usuario'  AND cu.id = t.criado_por_id
      LEFT JOIN barravips.modelos    cm ON t.criado_por_tipo = 'modelo'   AND cm.id = t.criado_por_id
      LEFT JOIN barravips.vendedores cv ON t.criado_por_tipo = 'vendedor' AND cv.id = t.criado_por_id
      LEFT JOIN barravips.usuarios   au ON t.atribuido_tipo  = 'usuario'  AND au.id = t.atribuido_id
      LEFT JOIN barravips.modelos    am ON t.atribuido_tipo  = 'modelo'   AND am.id = t.atribuido_id
      LEFT JOIN barravips.vendedores av ON t.atribuido_tipo  = 'vendedor' AND av.id = t.atribuido_id
"""


def _row_to_response(row: dict[str, Any]) -> TarefaResponse:
    atribuido: AtorRef | None = None
    if row["atribuido_tipo"] is not None:
        atribuido = AtorRef(
            tipo=row["atribuido_tipo"],
            id=row["atribuido_id"],
            nome=row["atribuido_nome"],
        )
    return TarefaResponse(
        id=row["id"],
        titulo=row["titulo"],
        descricao=row["descricao"],
        status=row["status"],
        prioridade=row["prioridade"],
        prazo=row["prazo"],
        criado_por=AtorRef(
            tipo=row["criado_por_tipo"],
            id=row["criado_por_id"],
            nome=row["criado_por_nome"],
        ),
        atribuido=atribuido,
        concluida_em=row["concluida_em"].isoformat() if row["concluida_em"] else None,
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


async def listar(
    conn: AsyncConnection[Any],
    *,
    status: str | None,
    prioridade: str | None = None,
    q: str | None = None,
    atribuido_tipo: str | None,
    atribuido_id: UUID | None,
    prazo: PrazoFiltro,
    limit: int,
) -> list[TarefaResponse]:
    filtros: list[str] = []
    params: list[Any] = []

    if status is not None:
        filtros.append("t.status = %s")
        params.append(status)

    if prioridade is not None:
        filtros.append("t.prioridade = %s")
        params.append(prioridade)

    if q:
        filtros.append("(t.titulo ILIKE %s OR t.descricao ILIKE %s)")
        like = f"%{q}%"
        params.extend([like, like])

    if atribuido_tipo is not None and atribuido_id is not None:
        filtros.append("t.atribuido_tipo = %s AND t.atribuido_id = %s")
        params.extend([atribuido_tipo, atribuido_id])

    if prazo == "hoje":
        filtros.append(f"t.prazo = {_HOJE_BRT}")
    elif prazo == "semana":
        filtros.append(f"t.prazo >= {_HOJE_BRT} AND t.prazo <= {_HOJE_BRT} + 6")
    elif prazo == "atrasadas":
        filtros.append(f"t.prazo < {_HOJE_BRT} AND t.status <> 'feita'")

    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    params.append(limit)

    sql = f"""
        {_SELECT_BASE}
        {where}
         ORDER BY (t.status = 'feita'),
                  t.prioridade DESC,
                  t.prazo ASC NULLS LAST,
                  t.created_at DESC
         LIMIT %s
    """
    result = await conn.execute(sql, params)
    rows = list(await result.fetchall())
    return [_row_to_response(row) for row in rows]


async def obter(conn: AsyncConnection[Any], tarefa_id: UUID) -> TarefaResponse | None:
    result = await conn.execute(f"{_SELECT_BASE} WHERE t.id = %s", (tarefa_id,))
    row = await result.fetchone()
    return _row_to_response(row) if row is not None else None


async def criar(
    conn: AsyncConnection[Any],
    *,
    titulo: str,
    descricao: str | None,
    prioridade: str,
    prazo: date | None,
    criado_por_tipo: str,
    criado_por_id: UUID,
    atribuido_tipo: str | None,
    atribuido_id: UUID | None,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.tarefas
            (titulo, descricao, prioridade, prazo,
             criado_por_tipo, criado_por_id, atribuido_tipo, atribuido_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            titulo,
            descricao,
            prioridade,
            prazo,
            criado_por_tipo,
            criado_por_id,
            atribuido_tipo,
            atribuido_id,
        ),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar(
    conn: AsyncConnection[Any],
    tarefa_id: UUID,
    campos: dict[str, Any],
) -> bool:
    """UPDATE dinâmico. `campos` já validado pelo service (chaves de coluna reais).

    Sincroniza `concluida_em` com `status`: vira `now()` ao concluir, NULL ao reabrir.
    """
    sets: list[str] = []
    params: list[Any] = []
    for col, val in campos.items():
        sets.append(f"{col} = %s")
        params.append(val)

    if "status" in campos:
        if campos["status"] == "feita":
            sets.append("concluida_em = now()")
        else:
            sets.append("concluida_em = NULL")

    if not sets:
        return True

    params.append(tarefa_id)
    result = await conn.execute(
        f"UPDATE barravips.tarefas SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0


async def excluir(conn: AsyncConnection[Any], tarefa_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM barravips.tarefas WHERE id = %s",
        (tarefa_id,),
    )
    return result.rowcount > 0


async def listar_responsaveis(conn: AsyncConnection[Any]) -> list[ResponsavelOpcao]:
    """Universo do seletor de responsável (rótulo). usuarios ativos + modelos não
    inativas + vendedores ativos (ADR 0012).
    """
    result = await conn.execute(
        """
        SELECT 'usuario' AS tipo, id, nome FROM barravips.usuarios WHERE ativo
        UNION ALL
        SELECT 'modelo' AS tipo, id, nome FROM barravips.modelos WHERE status <> 'inativa'
        UNION ALL
        SELECT 'vendedor' AS tipo, id, nome FROM barravips.vendedores WHERE ativo
        ORDER BY tipo, nome
        """
    )
    rows = list(await result.fetchall())
    return [ResponsavelOpcao(tipo=row["tipo"], id=row["id"], nome=row["nome"]) for row in rows]
