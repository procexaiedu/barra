from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.auth import UsuarioAtual
from barra.core.errors import NaoEncontrado
from barra.dominio.atendimentos.schemas import (
    CorrigirRegistroRequest,
    DevolverRequest,
    FecharRequest,
    PerderRequest,
)
from barra.dominio.escaladas.service import aplicar_comando

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def listar_atendimentos(
    conn: AsyncConnection[Any] = Depends(get_conn),
    estado: str | None = None,
    tipo_atendimento: str | None = None,
    urgencia: str | None = None,
    ia_pausada: bool | None = None,
    modelo_id: UUID | None = None,
    motivo_perda: str | None = None,
    motivo_escalada: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if estado:
        filtros.append("a.estado = %s")
        params.append(estado)
    else:
        filtros.append("a.estado NOT IN ('Fechado', 'Perdido')")
    if tipo_atendimento:
        filtros.append("a.tipo_atendimento = %s")
        params.append(tipo_atendimento)
    if urgencia:
        filtros.append("a.urgencia = %s")
        params.append(urgencia)
    if ia_pausada is not None:
        filtros.append("a.ia_pausada = %s")
        params.append(ia_pausada)
    if modelo_id:
        filtros.append("a.modelo_id = %s")
        params.append(modelo_id)
    if motivo_perda and estado == "Perdido":
        filtros.append("a.motivo_perda = %s")
        params.append(motivo_perda)
    if motivo_escalada and ia_pausada is True:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.escaladas e2 "
            "WHERE e2.atendimento_id = a.id "
            "AND e2.aberta_em = (SELECT MAX(e3.aberta_em) FROM barravips.escaladas e3 WHERE e3.atendimento_id = a.id) "
            "AND e2.motivo = %s)"
        )
        params.append(motivo_escalada)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s OR a.numero_curto::text = %s)")
        params.extend([f"%{q}%", f"%{q}%", q])
    if cursor:
        filtros.append("a.updated_at < %s::timestamptz")
        params.append(cursor)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT
          a.id, a.numero_curto, a.estado::text AS estado,
          a.tipo_atendimento::text AS tipo_atendimento, a.urgencia::text AS urgencia,
          a.ia_pausada, a.ia_pausada_motivo::text AS ia_pausada_motivo,
          a.responsavel_atual::text AS responsavel_atual, a.motivo_escalada,
          a.proxima_acao_esperada, a.updated_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          m.id AS modelo_id, m.nome AS modelo_nome
        FROM barravips.atendimentos a
        JOIN barravips.clientes c ON c.id = a.cliente_id
        JOIN barravips.modelos m ON m.id = a.modelo_id
        WHERE {" AND ".join(filtros)}
        ORDER BY a.updated_at DESC
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
                "numero_curto": row["numero_curto"],
                "cliente": {
                    "id": row["cliente_id"],
                    "nome": row["cliente_nome"],
                    "telefone": row["cliente_telefone"],
                },
                "modelo": {"id": row["modelo_id"], "nome": row["modelo_nome"]},
                "estado": row["estado"],
                "tipo_atendimento": row["tipo_atendimento"],
                "urgencia": row["urgencia"],
                "ia_pausada": row["ia_pausada"],
                "ia_pausada_motivo": row["ia_pausada_motivo"],
                "responsavel_atual": row["responsavel_atual"],
                "motivo_escalada": row["motivo_escalada"],
                "proxima_acao_esperada": row["proxima_acao_esperada"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/{atendimento_id}")
async def obter_atendimento(
    atendimento_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
    mensagens_limit: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    atendimento = await _fetch_one(
        conn,
        """
        SELECT a.*, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
               m.nome AS modelo_nome, m.percentual_repasse, b.inicio AS bloqueio_inicio,
               b.fim AS bloqueio_fim, b.estado::text AS bloqueio_estado
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
          LEFT JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    if atendimento is None:
        raise NaoEncontrado("Atendimento")

    mensagens = await _fetch_all(
        conn,
        """
        SELECT * FROM barravips.mensagens
         WHERE atendimento_id = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        (atendimento_id, mensagens_limit),
    )
    eventos = await _fetch_all(
        conn,
        "SELECT * FROM barravips.eventos WHERE atendimento_id = %s ORDER BY created_at DESC LIMIT 100",
        (atendimento_id,),
    )
    pix = await _fetch_all(
        conn,
        "SELECT * FROM barravips.comprovantes_pix WHERE atendimento_id = %s ORDER BY created_at DESC",
        (atendimento_id,),
    )
    escaladas = await _fetch_all(
        conn,
        "SELECT * FROM barravips.escaladas WHERE atendimento_id = %s ORDER BY aberta_em DESC",
        (atendimento_id,),
    )
    return {
        "atendimento": atendimento,
        "cliente": {
            "id": atendimento["cliente_id"],
            "nome": atendimento["cliente_nome"],
            "telefone": atendimento["cliente_telefone"],
        },
        "conversa": {"id": atendimento["conversa_id"]},
        "modelo": {"id": atendimento["modelo_id"], "nome": atendimento["modelo_nome"]},
        "bloqueio": None
        if atendimento["bloqueio_id"] is None
        else {
            "id": atendimento["bloqueio_id"],
            "inicio": atendimento["bloqueio_inicio"],
            "fim": atendimento["bloqueio_fim"],
            "estado": atendimento["bloqueio_estado"],
        },
        "mensagens": mensagens,
        "eventos": eventos,
        "comprovantes_pix": pix,
        "escaladas": escaladas,
    }


@router.post("/{atendimento_id}/devolver")
async def devolver_atendimento(
    atendimento_id: UUID,
    body: DevolverRequest,
    user: UsuarioAtual = Depends(get_user),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="devolver_para_ia",
        payload={"observacao": body.observacao, "usuario_id": str(user.id)},
    )
    return {"id": result.atendimento_id, "estado": result.estado, "ia_pausada": False}


@router.post("/{atendimento_id}/fechar")
async def fechar_atendimento(
    atendimento_id: UUID,
    body: FecharRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="registrar_fechado",
        payload={"valor_final": body.valor_final},
    )
    return {"id": result.atendimento_id, "estado": result.estado}


@router.post("/{atendimento_id}/perder")
async def perder_atendimento(
    atendimento_id: UUID,
    body: PerderRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="registrar_perdido",
        payload=body.model_dump(),
    )
    return {"id": result.atendimento_id, "estado": result.estado}


@router.post("/{atendimento_id}/corrigir-registro")
async def corrigir_registro(
    atendimento_id: UUID,
    body: CorrigirRegistroRequest,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    result = await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="corrigir_registro",
        payload=body.model_dump(),
    )
    return {"id": result.atendimento_id, "estado": result.estado}


async def _fetch_one(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _fetch_all(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
