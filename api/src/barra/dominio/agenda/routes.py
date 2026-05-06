from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.dominio.agenda.schemas import BloqueioCreate, BloqueioPatch, CancelarBloqueio

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("/bloqueios")
async def listar_bloqueios(
    inicio: datetime,
    fim: datetime,
    modelo_id: UUID | None = None,
    estado: str | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    if modelo_id:
        result = await conn.execute(
            "SELECT id, nome FROM barravips.modelos WHERE id = %s",
            (modelo_id,),
        )
        row = await result.fetchone()
        if not row:
            return {"modelo": None, "inicio": inicio, "fim": fim, "bloqueios": []}
        modelo = {"id": str(row["id"]), "nome": row["nome"]}
    else:
        modelo = None

    params: list[Any] = [fim, inicio]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND b.modelo_id = %s"
        params.append(modelo_id)
        
    filtro_estado = ""
    if estado:
        filtro_estado = "AND b.estado = %s"
        params.append(estado)
    result = await conn.execute(
        f"""
        SELECT
          b.*,
          b.estado::text AS estado,
          b.origem::text AS origem,
          a.id AS atendimento_id,
          a.numero_curto,
          a.estado::text AS atendimento_estado,
          a.valor_acordado,
          a.endereco,
          a.bairro,
          a.data_desejada,
          a.horario_desejado,
          a.tipo_atendimento::text AS tipo_atendimento,
          c.nome AS cliente_nome,
          c.telefone AS cliente_telefone,
          m.nome AS modelo_nome
          FROM barravips.bloqueios b
          LEFT JOIN barravips.atendimentos a ON a.id = b.atendimento_id
          LEFT JOIN barravips.clientes c ON c.id = a.cliente_id
          LEFT JOIN barravips.modelos m ON m.id = b.modelo_id
         WHERE b.inicio < %s
           AND b.fim > %s
           {filtro_modelo}
           {filtro_estado}
         ORDER BY b.inicio ASC
        """,
        params,
    )
    bloqueios = [_formatar_bloqueio(row) for row in await result.fetchall()]
    return {"modelo": modelo, "inicio": inicio, "fim": fim, "bloqueios": bloqueios}


@router.post("/bloqueios", status_code=201)
async def criar_bloqueio(
    body: BloqueioCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    if body.atendimento_id:
        res = await conn.execute(
            "SELECT modelo_id FROM barravips.atendimentos WHERE id = %s",
            (body.atendimento_id,),
        )
        at_row = await res.fetchone()
        if at_row is None:
            raise NaoEncontrado("Atendimento")
        if at_row["modelo_id"] != body.modelo_id:
            raise ConflitoEstado("atendimento_nao_pertence_ao_modelo")
    try:
        async with conn.transaction():
            result = await conn.execute(
                """
                INSERT INTO barravips.bloqueios (modelo_id, inicio, fim, origem, observacao, atendimento_id)
                VALUES (%s, %s, %s, 'painel_fernando', %s, %s)
                RETURNING *
                """,
                (body.modelo_id, body.inicio, body.fim, body.observacao, body.atendimento_id),
            )
            row = await result.fetchone()
            assert row is not None
            return cast(dict[str, Any], row)
    except ExclusionViolation as exc:
        raise ConflitoEstado("Bloqueio sobreposto.") from exc


@router.patch("/bloqueios/{bloqueio_id}")
async def editar_bloqueio(
    bloqueio_id: UUID,
    body: BloqueioPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    atual = await _bloqueio(conn, bloqueio_id)
    if atual is None:
        raise NaoEncontrado("Bloqueio")
    inicio = body.inicio or atual["inicio"]
    fim = body.fim or atual["fim"]
    if inicio >= fim:
        raise EntradaInvalida("INTERVALO_INVALIDO", "Inicio deve ser anterior ao fim.")
    try:
        async with conn.transaction():
            result = await conn.execute(
                """
                UPDATE barravips.bloqueios
                   SET inicio = %s, fim = %s, observacao = COALESCE(%s, observacao)
                 WHERE id = %s
                RETURNING *
                """,
                (inicio, fim, body.observacao, bloqueio_id),
            )
            row = await result.fetchone()
            assert row is not None
            return cast(dict[str, Any], row)
    except ExclusionViolation as exc:
        raise ConflitoEstado("Bloqueio sobreposto.") from exc


@router.post("/bloqueios/{bloqueio_id}/cancelar")
async def cancelar_bloqueio(
    bloqueio_id: UUID,
    body: CancelarBloqueio,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    atual = await _bloqueio(conn, bloqueio_id)
    if atual is None:
        raise NaoEncontrado("Bloqueio")
    if atual["estado"] == "concluido":
        raise ConflitoEstado("Bloqueio concluido nao pode ser cancelado.")
    if atual["estado"] == "em_atendimento" and not body.confirmar:
        raise ConflitoEstado(
            "Cancelamento em atendimento exige confirmacao.",
            {"campo": "confirmar"},
        )
    result = await conn.execute(
        """
        UPDATE barravips.bloqueios
           SET estado = 'cancelado'
         WHERE id = %s
        RETURNING *
        """,
        (bloqueio_id,),
    )
    row = await result.fetchone()
    assert row is not None
    return {"ok": True}


async def _bloqueio(conn: AsyncConnection[Any], bloqueio_id: UUID) -> dict[str, Any] | None:
    result = await conn.execute(
        "SELECT *, estado::text AS estado FROM barravips.bloqueios WHERE id = %s",
        (bloqueio_id,),
    )
    return await result.fetchone()


async def _modelo_ativa(conn: AsyncConnection[Any], modelo_id: UUID | None) -> dict[str, str] | None:
    if modelo_id is None:
        return None
    result = await conn.execute(
        "SELECT id, nome FROM barravips.modelos WHERE id = %s",
        (modelo_id,),
    )
    row = await result.fetchone()
    if row is None:
        return None
    return {"id": str(row["id"]), "nome": row["nome"]}


def _formatar_bloqueio(row: dict[str, Any]) -> dict[str, Any]:
    atendimento = None
    if row["atendimento_id"]:
        data_desejada = row.get("data_desejada")
        horario_desejado = row.get("horario_desejado")
        valor_acordado = row.get("valor_acordado")
        atendimento = {
            "id": str(row["atendimento_id"]),
            "numero_curto": row["numero_curto"],
            "cliente_nome": row["cliente_nome"],
            "cliente_telefone_formatado": _formatar_telefone(row["cliente_telefone"]),
            "estado": row["atendimento_estado"],
            "tipo_atendimento": row.get("tipo_atendimento"),
            "valor_acordado": str(valor_acordado) if valor_acordado is not None else None,
            "endereco": row.get("endereco"),
            "bairro": row.get("bairro"),
            "data_desejada": data_desejada.isoformat() if data_desejada is not None else None,
            "horario_desejado": str(horario_desejado) if horario_desejado is not None else None,
        }
    return {
        "id": str(row["id"]),
        "modelo_id": str(row["modelo_id"]),
        "modelo_nome": row.get("modelo_nome"),
        "inicio": row["inicio"],
        "fim": row["fim"],
        "estado": row["estado"],
        "origem": row["origem"],
        "observacao": row["observacao"],
        "atendimento_id": str(row["atendimento_id"]) if row["atendimento_id"] else None,
        "atendimento": atendimento,
    }


def _formatar_telefone(telefone: str | None) -> str:
    if not telefone:
        return ""
    digitos = "".join(ch for ch in telefone.split("@")[0] if ch.isdigit())
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return telefone.split("@")[0].removeprefix("+55").removeprefix("55")
