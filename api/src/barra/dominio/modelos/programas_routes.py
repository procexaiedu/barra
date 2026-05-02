from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.dominio.modelos.schemas import DuracaoCreate, DuracaoPatch, ProgramaCreate, ProgramaPatch

router = APIRouter(dependencies=[Depends(get_user)])
duracoes_router = APIRouter(dependencies=[Depends(get_user)])


def _serializar_programa(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "nome": row["nome"],
        "categoria": row["categoria"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _serializar_duracao(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "nome": row["nome"],
        "ordem": row["ordem"],
        "created_at": row["created_at"].isoformat(),
    }


# ── Programas ────────────────────────────────────────────────────────────────

@router.get("")
async def listar_programas(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    result = await conn.execute(
        "SELECT * FROM barravips.programas ORDER BY categoria NULLS FIRST, nome ASC",
        (),
    )
    rows = list(await result.fetchall())
    return [_serializar_programa(row) for row in rows]


@router.post("", status_code=201)
async def criar_programa(
    body: ProgramaCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    categoria = body.categoria.strip() if body.categoria else None
    result = await conn.execute(
        """
        INSERT INTO barravips.programas (nome, categoria)
        VALUES (%s, %s)
        RETURNING *
        """,
        (body.nome.strip(), categoria),
    )
    row = await result.fetchone()
    assert row is not None
    return _serializar_programa(row)


@router.patch("/{programa_id}")
async def editar_programa(
    programa_id: UUID,
    body: ProgramaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        result = await conn.execute(
            "SELECT * FROM barravips.programas WHERE id = %s",
            (programa_id,),
        )
        row = await result.fetchone()
        if row is None:
            raise NaoEncontrado("Programa")
        return _serializar_programa(row)
    if "nome" in updates:
        updates["nome"] = updates["nome"].strip()
    if updates.get("categoria"):
        updates["categoria"] = updates["categoria"].strip() or None
    set_sql = ", ".join([f"{key} = %s" for key in updates])
    params = list(updates.values()) + [programa_id]
    result = await conn.execute(
        f"UPDATE barravips.programas SET {set_sql} WHERE id = %s RETURNING *",
        params,
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Programa")
    return _serializar_programa(row)


@router.delete("/{programa_id}", status_code=204)
async def deletar_programa(
    programa_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    result = await conn.execute(
        "SELECT count(*) FROM barravips.modelo_programas WHERE programa_id = %s",
        (programa_id,),
    )
    row = await result.fetchone()
    if row and int(row["count"]) > 0:
        raise ConflitoEstado("Programa está vinculado a modelos. Desvincule antes de remover.")
    await conn.execute("DELETE FROM barravips.programas WHERE id = %s", (programa_id,))


# ── Durações ─────────────────────────────────────────────────────────────────

@duracoes_router.get("")
async def listar_duracoes(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    result = await conn.execute(
        "SELECT * FROM barravips.duracoes ORDER BY ordem ASC, nome ASC",
        (),
    )
    rows = list(await result.fetchall())
    return [_serializar_duracao(row) for row in rows]


@duracoes_router.post("", status_code=201)
async def criar_duracao(
    body: DuracaoCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        "INSERT INTO barravips.duracoes (nome, ordem) VALUES (%s, %s) RETURNING *",
        (body.nome.strip(), body.ordem),
    )
    row = await result.fetchone()
    assert row is not None
    return _serializar_duracao(row)


@duracoes_router.patch("/{duracao_id}")
async def editar_duracao(
    duracao_id: UUID,
    body: DuracaoPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        result = await conn.execute(
            "SELECT * FROM barravips.duracoes WHERE id = %s", (duracao_id,)
        )
        row = await result.fetchone()
        if row is None:
            raise NaoEncontrado("Duração")
        return _serializar_duracao(row)
    if "nome" in updates:
        updates["nome"] = updates["nome"].strip()
    set_sql = ", ".join([f"{key} = %s" for key in updates])
    params = list(updates.values()) + [duracao_id]
    result = await conn.execute(
        f"UPDATE barravips.duracoes SET {set_sql} WHERE id = %s RETURNING *",
        params,
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Duração")
    return _serializar_duracao(row)


@duracoes_router.delete("/{duracao_id}", status_code=204)
async def deletar_duracao(
    duracao_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    result = await conn.execute(
        "SELECT count(*) FROM barravips.modelo_programas WHERE duracao_id = %s",
        (duracao_id,),
    )
    row = await result.fetchone()
    if row and int(row["count"]) > 0:
        raise ConflitoEstado("Duração está em uso. Remova os vínculos antes.")
    await conn.execute("DELETE FROM barravips.duracoes WHERE id = %s", (duracao_id,))
