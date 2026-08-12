from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, NaoEncontrado
from barra.dominio.modelos.schemas import FeticheCreate, FetichePatch

router = APIRouter(dependencies=[Depends(get_user)])


def _serializar_fetiche(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "nome": row["nome"],
        "ordem": row["ordem"],
        # COMPOSIÇÃO (quem acompanha quem no encontro). Desde o ADR-0039 é CLASSIFICAÇÃO, não
        # regime de preço (o extra é o mesmo dos atos). Curado no catálogo global, não editável
        # pelo painel — vai ao front só para o aviso ao lado do campo de preço, que hoje diz
        # "digite o TOTAL do extra pelas duas".
        # Desde 11/08/2026 há um item por composição (acompanhante dele mulher/homem, dupla de
        # modelos, dois casais — migration 20260811232000) no lugar do par ambíguo "Casal"/
        # "Menage": vincular/desvincular AQUI é o que diz o que cada modelo faz, e o que ela não
        # tem vinculado a IA recusa sozinha (closed-world do `render_fetiches`). O painel é o
        # único caminho para isso — a migration deliberadamente não cria vínculo nenhum.
        "cobra_por_pessoa": bool(row["cobra_por_pessoa"]),
        "created_at": row["created_at"].isoformat(),
    }


@router.get("")
async def listar_fetiches(
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> list[dict[str, Any]]:
    result = await conn.execute(
        "SELECT * FROM barravips.fetiches ORDER BY ordem ASC, nome ASC",
        (),
    )
    rows = list(await result.fetchall())
    return [_serializar_fetiche(row) for row in rows]


@router.post("", status_code=201)
async def criar_fetiche(
    body: FeticheCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await conn.execute(
        "INSERT INTO barravips.fetiches (nome, ordem) VALUES (%s, %s) RETURNING *",
        (body.nome.strip(), body.ordem),
    )
    row = await result.fetchone()
    assert row is not None
    return _serializar_fetiche(row)


@router.patch("/{fetiche_id}")
async def editar_fetiche(
    fetiche_id: UUID,
    body: FetichePatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        result = await conn.execute("SELECT * FROM barravips.fetiches WHERE id = %s", (fetiche_id,))
        row = await result.fetchone()
        if row is None:
            raise NaoEncontrado("Fetiche")
        return _serializar_fetiche(row)
    if "nome" in updates:
        updates["nome"] = updates["nome"].strip()
    set_sql = ", ".join([f"{key} = %s" for key in updates])
    params = list(updates.values()) + [fetiche_id]
    result = await conn.execute(
        f"UPDATE barravips.fetiches SET {set_sql} WHERE id = %s RETURNING *",
        params,
    )
    row = await result.fetchone()
    if row is None:
        raise NaoEncontrado("Fetiche")
    return _serializar_fetiche(row)


@router.delete("/{fetiche_id}", status_code=204)
async def deletar_fetiche(
    fetiche_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> None:
    result = await conn.execute(
        "SELECT count(*) FROM barravips.modelo_fetiches WHERE fetiche_id = %s",
        (fetiche_id,),
    )
    row = await result.fetchone()
    if row and int(row["count"]) > 0:
        raise ConflitoEstado("Fetiche está vinculado a modelos. Desvincule antes de remover.")
    await conn.execute("DELETE FROM barravips.fetiches WHERE id = %s", (fetiche_id,))
