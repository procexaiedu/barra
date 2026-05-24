import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.dominio.clientes.schemas import ClienteCreate, ClientePatch

router = APIRouter(dependencies=[Depends(get_user)])

_TELEFONE_BR_RE = re.compile(r"^55\d{10,11}$")

PERIODOS_DIAS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/clientes")
async def listar_clientes(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: UUID | None = None,
    q: str | None = None,
    periodo: str | None = None,
    incluir_arquivados: bool = False,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if modelo_id:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.conversas cv "
            "WHERE cv.cliente_id = c.id AND cv.modelo_id = %s)"
        )
        params.append(modelo_id)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if periodo in PERIODOS_DIAS:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.atendimentos a "
            "WHERE a.cliente_id = c.id "
            f"AND a.created_at >= NOW() - INTERVAL '{PERIODOS_DIAS[periodo]} days')"
        )
    if not incluir_arquivados:
        filtros.append("c.arquivado_em IS NULL")
    if cursor:
        filtros.append("c.updated_at < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT c.id, c.nome, c.telefone, c.primeiro_contato_modelo_id,
               c.arquivado_em, c.created_at, c.updated_at,
               ag.total_atendimentos, ag.total_fechados,
               ag.valor_total, ag.ultima_atividade,
               ag.modelos_distintas, ag.modelo_predominante_nome
          FROM barravips.clientes c
          LEFT JOIN LATERAL (
            SELECT
              COUNT(*) AS total_atendimentos,
              COUNT(*) FILTER (WHERE a.estado = 'Fechado') AS total_fechados,
              COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0) AS valor_total,
              MAX(a.updated_at) AS ultima_atividade,
              COUNT(DISTINCT a.modelo_id) AS modelos_distintas,
              (SELECT m.nome
                 FROM barravips.atendimentos a2
                 JOIN barravips.modelos m ON m.id = a2.modelo_id
                WHERE a2.cliente_id = c.id
                GROUP BY m.id, m.nome
                ORDER BY COUNT(*) DESC, MAX(a2.updated_at) DESC
                LIMIT 1) AS modelo_predominante_nome
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
          ) ag ON TRUE
         WHERE {" AND ".join(filtros)}
         ORDER BY c.updated_at DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    next_cursor = rows[-1]["updated_at"].isoformat() if len(rows) > limit else None
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": row["id"],
                "nome": row["nome"],
                "telefone_mascarado": _mascarar_telefone(row["telefone"]),
                "primeiro_contato_modelo_id": row["primeiro_contato_modelo_id"],
                "arquivado_em": row["arquivado_em"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "total_atendimentos": row["total_atendimentos"] or 0,
                "valor_total": row["valor_total"] or 0,
                "ultima_atividade": row["ultima_atividade"],
                "modelos_distintas": row["modelos_distintas"] or 0,
                "modelo_predominante_nome": row["modelo_predominante_nome"],
                "recorrente": (row["total_fechados"] or 0) >= 2,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/clientes", status_code=201)
async def criar_cliente(
    body: ClienteCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    telefone = _normalizar_telefone_br(body.telefone)
    nome = body.nome.strip() if isinstance(body.nome, str) else None
    if nome == "":
        nome = None
    try:
        row = await _one(
            conn,
            """
            INSERT INTO barravips.clientes (nome, telefone)
            VALUES (%s, %s)
            RETURNING id, nome, telefone, primeiro_contato_modelo_id,
                      arquivado_em, created_at, updated_at
            """,
            (nome, telefone),
        )
    except UniqueViolation as exc:
        raise ConflitoEstado("telefone_duplicado") from exc
    assert row is not None
    return {
        "id": row["id"],
        "nome": row["nome"],
        "telefone": row["telefone"],
        "telefone_mascarado": _mascarar_telefone(row["telefone"]),
        "primeiro_contato_modelo_id": row["primeiro_contato_modelo_id"],
        "arquivado_em": row["arquivado_em"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/clientes/{cliente_id}")
async def obter_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT * FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    conversas = await _all(
        conn,
        """
        SELECT cv.id, cv.modelo_id, cv.recorrente, cv.ultimo_motivo_perda,
               cv.ultima_mensagem_em, cv.observacoes_internas,
               m.nome AS modelo_nome
          FROM barravips.conversas cv
          JOIN barravips.modelos m ON m.id = cv.modelo_id
         WHERE cv.cliente_id = %s
         ORDER BY cv.ultima_mensagem_em DESC NULLS LAST, cv.updated_at DESC
        """,
        (cliente_id,),
    )
    return {
        "cliente": {
            "id": cliente["id"],
            "nome": cliente["nome"],
            "telefone_mascarado": _mascarar_telefone(cliente["telefone"]),
            "primeiro_contato_modelo_id": cliente["primeiro_contato_modelo_id"],
            "arquivado_em": cliente["arquivado_em"],
            "created_at": cliente["created_at"],
            "updated_at": cliente["updated_at"],
        },
        "conversas": conversas,
    }


@router.patch("/clientes/{cliente_id}")
async def editar_cliente(
    cliente_id: UUID,
    body: ClientePatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        cliente = await _one(
            conn,
            "SELECT id, telefone FROM barravips.clientes WHERE id = %s",
            (cliente_id,),
        )
        if cliente is None:
            raise NaoEncontrado("Cliente")
        sets: list[str] = []
        valores: list[Any] = []
        if body.nome is not None or "nome" in body.model_fields_set:
            nome = body.nome.strip() if isinstance(body.nome, str) else None
            if nome == "":
                nome = None
            sets.append("nome = %s")
            valores.append(nome)
        if body.telefone is not None:
            telefone = _normalizar_telefone_br(body.telefone)
            # Seeds antigos têm '+5521...' e a normalização tira o '+'; comparamos só dígitos
            # para evitar UPDATE no-op que dispara UNIQUE contra outro cliente que já tem o normalizado.
            atual_digitos = re.sub(r"\D+", "", cliente["telefone"] or "")
            if telefone != atual_digitos:
                sets.append("telefone = %s")
                valores.append(telefone)
        if sets:
            valores.append(cliente_id)
            try:
                await conn.execute(
                    f"UPDATE barravips.clientes SET {', '.join(sets)} WHERE id = %s",
                    valores,
                )
            except UniqueViolation as exc:
                raise ConflitoEstado("telefone_duplicado") from exc
        atualizado = await _one(
            conn,
            "SELECT id, nome, telefone, arquivado_em FROM barravips.clientes WHERE id = %s",
            (cliente_id,),
        )
    assert atualizado is not None
    return {
        "id": atualizado["id"],
        "nome": atualizado["nome"],
        "telefone": atualizado["telefone"],
        "arquivado_em": atualizado["arquivado_em"],
    }


@router.post("/clientes/{cliente_id}/arquivar")
async def arquivar_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT id, arquivado_em FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    if cliente["arquivado_em"] is None:
        atualizado = await _one(
            conn,
            "UPDATE barravips.clientes SET arquivado_em = NOW() WHERE id = %s "
            "RETURNING id, arquivado_em",
            (cliente_id,),
        )
        assert atualizado is not None
        return {"id": atualizado["id"], "arquivado_em": atualizado["arquivado_em"]}
    return {"id": cliente["id"], "arquivado_em": cliente["arquivado_em"]}


@router.post("/clientes/{cliente_id}/desarquivar")
async def desarquivar_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT id, arquivado_em FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    if cliente["arquivado_em"] is not None:
        await conn.execute(
            "UPDATE barravips.clientes SET arquivado_em = NULL WHERE id = %s",
            (cliente_id,),
        )
    return {"id": cliente["id"], "arquivado_em": None}


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())


def _mascarar_telefone(telefone: str | None) -> str | None:
    if not telefone:
        return None
    return telefone[:3] + "*****" + telefone[-4:]


def _normalizar_telefone_br(telefone: str) -> str:
    digitos = re.sub(r"\D+", "", telefone or "")
    if not _TELEFONE_BR_RE.match(digitos):
        raise EntradaInvalida(
            code="TELEFONE_INVALIDO",
            message="Telefone invalido. Use formato E.164 BR (55 + DDD + numero).",
        )
    return digitos
