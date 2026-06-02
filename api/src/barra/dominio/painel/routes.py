"""Endpoint agregado GET /painel/resumo para o Painel Geral."""

from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user

router = APIRouter(dependencies=[Depends(get_user)])

BRT = timezone(timedelta(hours=-3))


def _hoje_brt() -> tuple[datetime, datetime]:
    agora = datetime.now(BRT)
    inicio = datetime.combine(agora.date(), time.min, tzinfo=BRT)
    fim = datetime.combine(agora.date(), time.max, tzinfo=BRT)
    return inicio, fim


def _ontem_brt() -> tuple[datetime, datetime]:
    agora = datetime.now(BRT)
    ontem = agora.date() - timedelta(days=1)
    inicio = datetime.combine(ontem, time.min, tzinfo=BRT)
    fim = datetime.combine(ontem, time.max, tzinfo=BRT)
    return inicio, fim


def _formatar_telefone(telefone: str | None) -> str:
    if not telefone:
        return ""
    digitos = (
        telefone.replace("+", "")
        .replace("-", "")
        .replace(" ", "")
        .replace("(", "")
        .replace(")", "")
    )
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return telefone


@router.get("/resumo")
async def painel_resumo(
    modelo_id: list[UUID] | None = Query(None),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    agora = datetime.now(BRT)
    inicio_dia, fim_dia = _hoje_brt()

    modelo_result = await conn.execute(
        """
        SELECT id, nome, evolution_instance_id, evolution_status
          FROM barravips.modelos
         WHERE status IN ('ativa', 'pausada')
         ORDER BY CASE status WHEN 'ativa' THEN 0 ELSE 1 END, created_at ASC
        """
    )
    modelos_ativas = [
        {
            "id": str(m["id"]),
            "nome": m["nome"],
            "evolution_instance_id": m["evolution_instance_id"],
            "evolution_status": m["evolution_status"] or "desconectado",
        }
        for m in await modelo_result.fetchall()
    ]

    # Filtro de modelo para as queries abaixo
    filtro_modelo_sql = "AND a.modelo_id = ANY(%s)" if modelo_id else ""
    filtro_modelo_params: tuple[Any, ...] = (modelo_id,) if modelo_id else ()

    cards_result = await conn.execute(
        f"""
        SELECT
          a.id AS atendimento_id,
          a.numero_curto,
          c.nome AS cliente_nome,
          c.telefone AS cliente_telefone,
          a.ia_pausada_motivo::text AS ia_pausada_motivo,
          a.motivo_escalada,
          a.proxima_acao_esperada,
          a.responsavel_atual::text AS responsavel_atual,
          a.updated_at AS ia_pausada_em,
          a.tipo_atendimento::text AS tipo_atendimento,
          a.foto_portaria_em,
          a.duracao_horas,
          a.data_desejada,
          a.horario_desejado,
          m.nome AS modelo_nome
        FROM barravips.atendimentos a
        JOIN barravips.clientes c ON c.id = a.cliente_id
        JOIN barravips.modelos m ON m.id = a.modelo_id
        WHERE a.ia_pausada = true
          AND a.ia_pausada_motivo IN ('pix_em_revisao', 'modelo_em_atendimento', 'handoff_ia')
          {filtro_modelo_sql}
        ORDER BY a.updated_at ASC NULLS LAST
        """,
        filtro_modelo_params,
    )
    cards_rows = list(await cards_result.fetchall())

    cards_destaque: list[dict[str, Any]] = []
    for row in cards_rows:
        previsao = _calcular_previsao(row)
        expirado = previsao is not None and agora > previsao

        if row["ia_pausada_motivo"] == "modelo_em_atendimento" and not expirado:
            continue

        cards_destaque.append(
            {
                "atendimento_id": str(row["atendimento_id"]),
                "numero_curto": row["numero_curto"],
                "cliente_nome": row["cliente_nome"],
                "cliente_telefone_formatado": _formatar_telefone(row["cliente_telefone"]),
                "ia_pausada_motivo": row["ia_pausada_motivo"],
                "motivo_escalada": row["motivo_escalada"],
                "proxima_acao_esperada": row["proxima_acao_esperada"],
                "responsavel_atual": row["responsavel_atual"],
                "ia_pausada_em": row["ia_pausada_em"].isoformat() if row["ia_pausada_em"] else None,
                "previsao_termino": previsao.isoformat() if previsao else None,
                "expirado": expirado,
                "modelo_nome": row["modelo_nome"],
            }
        )

    ordem_motivo = {"pix_em_revisao": 0, "handoff_ia": 1, "modelo_em_atendimento": 2}
    cards_destaque.sort(
        key=lambda c: (ordem_motivo.get(c["ia_pausada_motivo"], 9), c["ia_pausada_em"] or "")
    )

    filtro_modelo_aten = "AND modelo_id = ANY(%s)" if modelo_id else ""

    abertos_result = await conn.execute(
        f"""
        SELECT COUNT(*) AS n
          FROM barravips.atendimentos
         WHERE estado NOT IN ('Fechado', 'Perdido')
           {filtro_modelo_aten}
        """,
        filtro_modelo_params,
    )
    abertos_row = await abertos_result.fetchone()
    abertos = abertos_row["n"] if abertos_row else 0

    filtro_modelo_eventos = "AND a.modelo_id = ANY(%s)" if modelo_id else ""

    fechamentos_result = await conn.execute(
        f"""
        SELECT COUNT(DISTINCT a.id) AS n
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
         WHERE a.estado = 'Fechado'
           AND e.tipo = 'fechado_registrado'
           AND e.created_at >= %s
           AND e.created_at <= %s
           {filtro_modelo_eventos}
        """,
        (inicio_dia, fim_dia, *filtro_modelo_params),
    )
    fechamentos_row = await fechamentos_result.fetchone()
    fechamentos_hoje = fechamentos_row["n"] if fechamentos_row else 0

    perdas_result = await conn.execute(
        f"""
        SELECT COUNT(DISTINCT a.id) AS n
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
         WHERE a.estado = 'Perdido'
           AND e.tipo = 'perdido_registrado'
           AND e.created_at >= %s
           AND e.created_at <= %s
           {filtro_modelo_eventos}
        """,
        (inicio_dia, fim_dia, *filtro_modelo_params),
    )
    perdas_row = await perdas_result.fetchone()
    perdas_hoje = perdas_row["n"] if perdas_row else 0

    valor_result = await conn.execute(
        f"""
        SELECT COALESCE(SUM(a.valor_final), 0) AS total
          FROM barravips.atendimentos a
         WHERE a.estado = 'Fechado'
           AND EXISTS (
             SELECT 1 FROM barravips.eventos e
              WHERE e.atendimento_id = a.id
                AND e.tipo = 'fechado_registrado'
                AND e.created_at >= %s
                AND e.created_at <= %s
           )
           {filtro_modelo_eventos}
        """,
        (inicio_dia, fim_dia, *filtro_modelo_params),
    )
    valor_row = await valor_result.fetchone()
    valor_bruto = float(valor_row["total"]) if valor_row else 0.0

    lucro_result = await conn.execute(
        f"""
        SELECT COALESCE(SUM(
          (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
        ), 0) AS lucro
          FROM barravips.atendimentos a
         WHERE a.estado = 'Fechado'
           AND EXISTS (
             SELECT 1 FROM barravips.eventos e
              WHERE e.atendimento_id = a.id
                AND e.tipo = 'fechado_registrado'
                AND e.created_at >= %s
                AND e.created_at <= %s
           )
           {filtro_modelo_eventos}
        """,
        (inicio_dia, fim_dia, *filtro_modelo_params),
    )
    lucro_row = await lucro_result.fetchone()
    lucro_hoje = float(lucro_row["lucro"]) if lucro_row else 0.0

    ticket_medio = (valor_bruto / fechamentos_hoje) if fechamentos_hoje > 0 else None
    total_conversao = fechamentos_hoje + perdas_hoje
    taxa_conversao = (fechamentos_hoje / total_conversao * 100) if total_conversao > 0 else None

    inicio_ontem, fim_ontem = _ontem_brt()
    ontem_result = await conn.execute(
        f"""
        SELECT
          COUNT(DISTINCT a.id) FILTER (WHERE a.estado = 'Fechado') AS fechamentos,
          COUNT(DISTINCT a.id) FILTER (WHERE a.estado = 'Perdido') AS perdas,
          COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0) AS valor_bruto
          FROM barravips.atendimentos a
         WHERE a.estado IN ('Fechado', 'Perdido')
           AND (
             (a.estado = 'Fechado' AND EXISTS (
               SELECT 1 FROM barravips.eventos e
                WHERE e.atendimento_id = a.id
                  AND e.tipo = 'fechado_registrado'
                  AND e.created_at >= %s
                  AND e.created_at <= %s
             ))
             OR
             (a.estado = 'Perdido' AND EXISTS (
               SELECT 1 FROM barravips.eventos e
                WHERE e.atendimento_id = a.id
                  AND e.tipo = 'perdido_registrado'
                  AND e.created_at >= %s
                  AND e.created_at <= %s
             ))
           )
           {filtro_modelo_eventos}
        """,
        (inicio_ontem, fim_ontem, inicio_ontem, fim_ontem, *filtro_modelo_params),
    )
    ontem_row = await ontem_result.fetchone()
    fechamentos_ontem = int(ontem_row["fechamentos"]) if ontem_row else 0
    perdas_ontem = int(ontem_row["perdas"]) if ontem_row else 0
    valor_ontem = float(ontem_row["valor_bruto"]) if ontem_row else 0.0

    pix_filtro = "AND a.modelo_id = ANY(%s)" if modelo_id else ""
    pix_result = await conn.execute(
        f"""
        SELECT COUNT(*) AS n
          FROM barravips.comprovantes_pix p
          JOIN barravips.atendimentos a ON a.id = p.atendimento_id
         WHERE p.decisao_pipeline = 'em_revisao'
           AND p.decisao_final IS NULL
           {pix_filtro}
        """,
        filtro_modelo_params,
    )
    pix_row = await pix_result.fetchone()
    pix_pendentes = pix_row["n"] if pix_row else 0

    filtro_bloqueio = "AND b.modelo_id = ANY(%s)" if modelo_id else ""
    agenda_result = await conn.execute(
        f"""
        SELECT
          b.id, b.modelo_id, b.inicio, b.fim,
          b.estado::text AS estado,
          b.origem::text AS origem,
          c.nome AS cliente_nome,
          b.observacao,
          b.atendimento_id,
          m.nome AS modelo_nome
        FROM barravips.bloqueios b
        JOIN barravips.modelos m ON m.id = b.modelo_id
        LEFT JOIN barravips.atendimentos a ON a.id = b.atendimento_id
        LEFT JOIN barravips.clientes c ON c.id = a.cliente_id
        WHERE b.inicio <= %s
          AND b.fim >= %s
          {filtro_bloqueio}
        ORDER BY b.inicio ASC
        """,
        (fim_dia, inicio_dia, *filtro_modelo_params),
    )
    agenda_rows = list(await agenda_result.fetchall())

    agenda_dia = [
        {
            "id": str(row["id"]),
            "modelo_id": str(row["modelo_id"]),
            "inicio": row["inicio"].isoformat(),
            "fim": row["fim"].isoformat(),
            "estado": row["estado"],
            "origem": row["origem"],
            "cliente_nome": row["cliente_nome"],
            "observacao": row["observacao"],
            "atendimento_id": str(row["atendimento_id"]) if row["atendimento_id"] else None,
            "modelo_nome": row["modelo_nome"],
        }
        for row in agenda_rows
    ]

    return {
        "modelos_ativas": modelos_ativas,
        "cards_destaque": cards_destaque,
        "metricas_dia": {
            "abertos": abertos,
            "fechamentos_hoje": fechamentos_hoje,
            "perdas_hoje": perdas_hoje,
            "valor_bruto_hoje_brl": valor_bruto,
            "lucro_hoje_brl": lucro_hoje,
            "ticket_medio_brl": ticket_medio,
            "taxa_conversao_pct": taxa_conversao,
            "pix_em_revisao_pendentes": pix_pendentes,
            "tendencia": {
                "fechamentos_delta": fechamentos_hoje - fechamentos_ontem,
                "fechamentos_ontem": fechamentos_ontem,
                "perdas_delta": perdas_hoje - perdas_ontem,
                "perdas_ontem": perdas_ontem,
                "valor_bruto_delta_brl": valor_bruto - valor_ontem,
                "valor_bruto_ontem_brl": valor_ontem,
            },
        },
        "agenda_dia": agenda_dia,
        "servidor_em": agora.isoformat(),
    }


@router.get("/detalhe/abertos")
async def painel_detalhe_abertos(
    modelo_id: list[UUID] | None = Query(None),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    filtro = "AND a.modelo_id = ANY(%s)" if modelo_id else ""
    params: tuple[Any, ...] = (modelo_id,) if modelo_id else ()

    result = await conn.execute(
        f"""
        SELECT a.id, a.numero_curto, c.nome AS cliente_nome,
               a.estado::text AS estado, m.nome AS modelo_nome
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.estado NOT IN ('Fechado', 'Perdido')
           {filtro}
         ORDER BY a.created_at ASC
         LIMIT 50
        """,
        params,
    )
    rows = await result.fetchall()
    agora = datetime.now(BRT)
    return {
        "itens": [
            {
                "atendimento_id": str(row["id"]),
                "numero_curto": row["numero_curto"],
                "cliente_nome": row["cliente_nome"],
                "estado": row["estado"],
                "modelo_nome": row["modelo_nome"],
            }
            for row in rows
        ],
        "servidor_em": agora.isoformat(),
    }


@router.get("/detalhe/fechamentos-hoje")
async def painel_detalhe_fechamentos(
    modelo_id: list[UUID] | None = Query(None),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    inicio_dia, fim_dia = _hoje_brt()
    filtro = "AND a.modelo_id = ANY(%s)" if modelo_id else ""
    params: tuple[Any, ...] = (inicio_dia, fim_dia, *((modelo_id,) if modelo_id else ()))

    result = await conn.execute(
        f"""
        SELECT a.id, a.numero_curto, c.nome AS cliente_nome,
               a.valor_final, a.percentual_repasse_snapshot, m.nome AS modelo_nome
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.estado = 'Fechado'
           AND EXISTS (
             SELECT 1 FROM barravips.eventos e
              WHERE e.atendimento_id = a.id
                AND e.tipo = 'fechado_registrado'
                AND e.created_at >= %s
                AND e.created_at <= %s
           )
           {filtro}
         ORDER BY a.updated_at DESC
         LIMIT 50
        """,
        params,
    )
    rows = await result.fetchall()
    agora = datetime.now(BRT)
    itens = []
    for row in rows:
        vf = float(row["valor_final"]) if row["valor_final"] is not None else None
        pct = (
            float(row["percentual_repasse_snapshot"])
            if row["percentual_repasse_snapshot"] is not None
            else None
        )
        lucro = (vf * (1 - pct / 100)) if vf is not None and pct is not None else vf
        itens.append(
            {
                "atendimento_id": str(row["id"]),
                "numero_curto": row["numero_curto"],
                "cliente_nome": row["cliente_nome"],
                "valor_final": vf,
                "lucro": lucro,
                "modelo_nome": row["modelo_nome"],
            }
        )
    return {"itens": itens, "servidor_em": agora.isoformat()}


@router.get("/detalhe/perdas-hoje")
async def painel_detalhe_perdas(
    modelo_id: list[UUID] | None = Query(None),
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    inicio_dia, fim_dia = _hoje_brt()
    filtro = "AND a.modelo_id = ANY(%s)" if modelo_id else ""
    params: tuple[Any, ...] = (inicio_dia, fim_dia, *((modelo_id,) if modelo_id else ()))

    result = await conn.execute(
        f"""
        SELECT a.id, a.numero_curto, c.nome AS cliente_nome,
               a.motivo_perda::text AS motivo_perda, m.nome AS modelo_nome
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.estado = 'Perdido'
           AND EXISTS (
             SELECT 1 FROM barravips.eventos e
              WHERE e.atendimento_id = a.id
                AND e.tipo = 'perdido_registrado'
                AND e.created_at >= %s
                AND e.created_at <= %s
           )
           {filtro}
         ORDER BY a.updated_at DESC
         LIMIT 50
        """,
        params,
    )
    rows = await result.fetchall()
    agora = datetime.now(BRT)
    return {
        "itens": [
            {
                "atendimento_id": str(row["id"]),
                "numero_curto": row["numero_curto"],
                "cliente_nome": row["cliente_nome"],
                "motivo_perda": row["motivo_perda"],
                "modelo_nome": row["modelo_nome"],
            }
            for row in rows
        ],
        "servidor_em": agora.isoformat(),
    }


def _calcular_previsao(row: dict[str, Any]) -> datetime | None:
    tipo = row.get("tipo_atendimento")
    duracao = row.get("duracao_horas")
    if duracao is None:
        return None

    if tipo == "interno" and row.get("foto_portaria_em"):
        foto_em: datetime = row["foto_portaria_em"]
        return foto_em + timedelta(hours=float(duracao))

    if tipo == "externo" and row.get("data_desejada") and row.get("horario_desejado"):
        dt = datetime.combine(row["data_desejada"], row["horario_desejado"], tzinfo=BRT)
        return dt + timedelta(hours=float(duracao))

    return None
