import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import NaoEncontrado
from barra.dominio.conversas.schemas import ConversaPatch

router = APIRouter(dependencies=[Depends(get_user)])

PERIODOS_DIAS = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/conversas")
async def listar_conversas(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: UUID | None = None,
    recorrente: bool | None = None,
    motivo_perda: str | None = None,
    periodo: str | None = None,
    q: str | None = None,
    ordenar_por: Literal["recente", "inatividade"] = "recente",
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if modelo_id:
        filtros.append("cv.modelo_id = %s")
        params.append(modelo_id)
    if recorrente is not None:
        filtros.append("cv.recorrente = %s")
        params.append(recorrente)
    if motivo_perda:
        filtros.append("cv.ultimo_motivo_perda = %s")
        params.append(motivo_perda)
    if periodo in PERIODOS_DIAS:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.atendimentos a "
            "WHERE a.conversa_id = cv.id "
            f"AND a.created_at >= NOW() - INTERVAL '{PERIODOS_DIAS[periodo]} days')"
        )
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if cursor:
        if ordenar_por == "inatividade":
            c = json.loads(cursor)
            cursor_id, cursor_ts = c["id"], c["ts"]
            if cursor_ts is None:
                filtros.append("(ufem.ts IS NULL AND cv.id > %s::uuid OR ufem.ts IS NOT NULL)")
                params.append(cursor_id)
            else:
                filtros.append(
                    "(ufem.ts > %s::timestamptz OR (ufem.ts = %s::timestamptz AND cv.id > %s::uuid))"
                )
                params.extend([cursor_ts, cursor_ts, cursor_id])
        else:
            filtros.append("cv.ultima_mensagem_em < %s::timestamptz")
            params.append(cursor)
    params.append(limit + 1)
    order_clause = (
        "ufem.ts ASC NULLS FIRST, cv.id ASC"
        if ordenar_por == "inatividade"
        else "cv.ultima_mensagem_em DESC NULLS LAST, cv.created_at DESC"
    )
    result = await conn.execute(
        f"""
        SELECT
          cv.id, cv.recorrente, cv.ultimo_motivo_perda::text AS ultimo_motivo_perda,
          cv.ultima_mensagem_em, cv.ultima_mensagem_direcao::text AS ultima_mensagem_direcao,
          cv.created_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          m.id AS modelo_id, m.nome AS modelo_nome,
          ult.id AS ult_id, ult.numero_curto AS ult_numero_curto,
          ult.estado AS ult_estado, ult.created_at AS ult_created_at,
          ult.valor_final AS ult_valor_final, ult.motivo_perda AS ult_motivo_perda,
          EXISTS (
            SELECT 1 FROM barravips.atendimentos ab
             WHERE ab.conversa_id = cv.id
               AND ab.estado NOT IN ('Fechado', 'Perdido')
          ) AS tem_atendimento_aberto,
          ufem.ts AS ultimo_fechamento_em
        FROM barravips.conversas cv
        JOIN barravips.clientes c ON c.id = cv.cliente_id
        JOIN barravips.modelos m ON m.id = cv.modelo_id
        LEFT JOIN LATERAL (
          SELECT a.id, a.numero_curto, a.estado::text AS estado, a.created_at,
                 a.valor_final, a.motivo_perda::text AS motivo_perda
            FROM barravips.atendimentos a
           WHERE a.conversa_id = cv.id
           ORDER BY a.created_at DESC
           LIMIT 1
        ) ult ON TRUE
        LEFT JOIN LATERAL (
          SELECT MAX(a.updated_at) AS ts
          FROM barravips.atendimentos a
          WHERE a.conversa_id = cv.id AND a.estado = 'Fechado'
        ) ufem ON TRUE
        WHERE {" AND ".join(filtros)}
        ORDER BY {order_clause}
        LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    if len(rows) > limit:
        last = rows[limit - 1]
        if ordenar_por == "inatividade":
            ts = last["ultimo_fechamento_em"]
            next_cursor: str | None = json.dumps(
                {"ts": ts.isoformat() if ts else None, "id": str(last["id"])}
            )
        else:
            ts = last["ultima_mensagem_em"]
            next_cursor = ts.isoformat() if ts is not None else None
    else:
        next_cursor = None
    rows = rows[:limit]
    items = [
        {
            "id": row["id"],
            "cliente": {
                "id": row["cliente_id"],
                "nome": row["cliente_nome"],
                "telefone": row["cliente_telefone"],
            },
            "modelo": {"id": row["modelo_id"], "nome": row["modelo_nome"]},
            "recorrente": row["recorrente"],
            "ultima_mensagem_em": row["ultima_mensagem_em"],
            "ultima_mensagem_direcao": row["ultima_mensagem_direcao"],
            "ultimo_motivo_perda": row["ultimo_motivo_perda"],
            "ultimo_atendimento": None
            if row["ult_id"] is None
            else {
                "numero_curto": row["ult_numero_curto"],
                "estado": row["ult_estado"],
                "created_at": row["ult_created_at"],
                "valor_final": row["ult_valor_final"],
                "motivo_perda": row["ult_motivo_perda"],
            },
            "tem_atendimento_aberto": row["tem_atendimento_aberto"],
            "ultimo_fechamento_em": row["ultimo_fechamento_em"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


@router.get("/conversas/{conversa_id}")
async def obter_conversa(
    conversa_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    conversa = await _one(
        conn,
        """
        SELECT
          cv.id, cv.recorrente, cv.observacoes_internas,
          cv.ultimo_motivo_perda::text AS ultimo_motivo_perda,
          cv.ultima_mensagem_em,
          cv.ultima_mensagem_direcao::text AS ultima_mensagem_direcao,
          cv.created_at,
          c.id AS cliente_id, c.nome AS cliente_nome, c.telefone AS cliente_telefone,
          c.created_at AS cliente_created_at,
          mp.nome AS primeiro_contato_modelo_nome,
          m.id AS modelo_id, m.nome AS modelo_nome
        FROM barravips.conversas cv
        JOIN barravips.clientes c ON c.id = cv.cliente_id
        JOIN barravips.modelos m ON m.id = cv.modelo_id
        LEFT JOIN barravips.modelos mp ON mp.id = c.primeiro_contato_modelo_id
        WHERE cv.id = %s
        """,
        (conversa_id,),
    )
    if conversa is None:
        raise NaoEncontrado("Conversa")

    aberto = await _one(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado,
               tipo_atendimento::text AS tipo_atendimento,
               urgencia::text AS urgencia,
               valor_acordado, proxima_acao_esperada
          FROM barravips.atendimentos
         WHERE conversa_id = %s
           AND estado NOT IN ('Fechado', 'Perdido')
         LIMIT 1
        """,
        (conversa_id,),
    )

    historico = await _all(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado, valor_final,
               motivo_perda::text AS motivo_perda, motivo_perda_obs, created_at
          FROM barravips.atendimentos
         WHERE conversa_id = %s
           AND estado IN ('Fechado', 'Perdido')
         ORDER BY created_at DESC
        """,
        (conversa_id,),
    )

    modelo_preferida = await _one(
        conn,
        """
        SELECT m.id, m.nome
        FROM barravips.atendimentos a
        JOIN barravips.conversas cv ON cv.id = a.conversa_id
        JOIN barravips.modelos m ON m.id = cv.modelo_id
        WHERE cv.cliente_id = %s AND cv.modelo_id = %s AND a.estado = 'Fechado'
        GROUP BY m.id, m.nome
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (conversa["cliente_id"], conversa["modelo_id"]),
    )

    tipo_atendimento_row = await _one(
        conn,
        """
        SELECT a.tipo_atendimento::text AS tipo_atendimento
        FROM barravips.atendimentos a
        JOIN barravips.conversas cv ON cv.id = a.conversa_id
        WHERE cv.cliente_id = %s
          AND cv.modelo_id = %s
          AND a.estado = 'Fechado'
          AND a.tipo_atendimento IS NOT NULL
        GROUP BY a.tipo_atendimento
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (conversa["cliente_id"], conversa["modelo_id"]),
    )

    programa_preferido = await _one(
        conn,
        """
        SELECT p.id, p.nome
        FROM barravips.atendimento_servicos ats
        JOIN barravips.atendimentos a ON a.id = ats.atendimento_id
        JOIN barravips.conversas cv ON cv.id = a.conversa_id
        JOIN barravips.programas p ON p.id = ats.programa_id
        WHERE cv.cliente_id = %s AND cv.modelo_id = %s AND a.estado = 'Fechado'
        GROUP BY p.id, p.nome
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (conversa["cliente_id"], conversa["modelo_id"]),
    )

    duracao_preferida = await _one(
        conn,
        """
        SELECT d.id, d.nome
        FROM barravips.atendimento_servicos ats
        JOIN barravips.atendimentos a ON a.id = ats.atendimento_id
        JOIN barravips.conversas cv ON cv.id = a.conversa_id
        JOIN barravips.duracoes d ON d.id = ats.duracao_id
        WHERE cv.cliente_id = %s AND cv.modelo_id = %s AND a.estado = 'Fechado'
        GROUP BY d.id, d.nome
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (conversa["cliente_id"], conversa["modelo_id"]),
    )

    forma_pagamento_row = await _one(
        conn,
        """
        SELECT a.forma_pagamento::text AS forma_pagamento
        FROM barravips.atendimentos a
        JOIN barravips.conversas cv ON cv.id = a.conversa_id
        WHERE cv.cliente_id = %s
          AND cv.modelo_id = %s
          AND a.estado = 'Fechado'
          AND a.forma_pagamento IS NOT NULL
        GROUP BY a.forma_pagamento
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (conversa["cliente_id"], conversa["modelo_id"]),
    )

    return {
        "conversa": {
            "id": conversa["id"],
            "recorrente": conversa["recorrente"],
            "observacoes_internas": conversa["observacoes_internas"],
            "ultimo_motivo_perda": conversa["ultimo_motivo_perda"],
            "ultima_mensagem_em": conversa["ultima_mensagem_em"],
            "ultima_mensagem_direcao": conversa["ultima_mensagem_direcao"],
            "created_at": conversa["created_at"],
        },
        "cliente": {
            "id": conversa["cliente_id"],
            "nome": conversa["cliente_nome"],
            "telefone": conversa["cliente_telefone"],
            "primeiro_contato_modelo_nome": conversa["primeiro_contato_modelo_nome"],
            "created_at": conversa["cliente_created_at"],
            "modelo_preferida": None
            if modelo_preferida is None
            else {"id": modelo_preferida["id"], "nome": modelo_preferida["nome"]},
            "tipo_atendimento_mais_frequente": tipo_atendimento_row["tipo_atendimento"]
            if tipo_atendimento_row
            else None,
            "programa_preferido": None
            if programa_preferido is None
            else {"id": programa_preferido["id"], "nome": programa_preferido["nome"]},
            "duracao_preferida": None
            if duracao_preferida is None
            else {"id": duracao_preferida["id"], "nome": duracao_preferida["nome"]},
            "forma_pagamento_preferida": forma_pagamento_row["forma_pagamento"]
            if forma_pagamento_row
            else None,
        },
        "modelo": {"id": conversa["modelo_id"], "nome": conversa["modelo_nome"]},
        "atendimento_aberto": None if aberto is None else aberto,
        "historico_atendimentos": historico,
    }


@router.patch("/conversas/{conversa_id}")
async def editar_conversa(
    conversa_id: UUID,
    body: ConversaPatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        existe = await _one(
            conn, "SELECT id FROM barravips.conversas WHERE id = %s", (conversa_id,)
        )
        if existe is None:
            raise NaoEncontrado("Conversa")
        valor = body.observacoes_internas
        if isinstance(valor, str):
            valor = valor.strip() or None
        await conn.execute(
            "UPDATE barravips.conversas SET observacoes_internas = %s WHERE id = %s",
            (valor, conversa_id),
        )
    return {"id": str(conversa_id), "observacoes_internas": valor}


async def _one(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())
