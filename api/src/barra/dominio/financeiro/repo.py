"""SQL puro psycopg3 do Módulo Financeiro (ADR 0011 / 0002).

Receita = projeção sobre `barravips.atendimentos` JOIN `barravips.eventos`
(tipo='fechado_registrado'). Repasses pagos têm tabela própria. Fórmulas de
líquido/repasse são as MESMAS do `dashboard/routes.py:_fechamentos` e
`painel/routes.py:198-217` — manter sincronizadas, divergir = bug.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.janela import Janela
from barra.dominio.financeiro.schemas import (
    AtendimentoSemSnapshotLinha,
    ContextoCliente,
    ContextoModelo,
    ContextoModeloDia,
    FinanceiroResumo,
    ReceitaContextoResponse,
    ReceitaLinha,
    RepassePagoResponse,
    SaldoModelo,
)

# =============================================================================
# Resumo
# =============================================================================


async def resumo_periodo(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_ids: list[UUID] | None,
) -> FinanceiroResumo:
    """Agregado da janela: bruto, líquido, repasse calc/pago/saldo.

    Receita filtra por evento `fechado_registrado.created_at` (regime caixa,
    ADR 0011). Pagamentos filtram por `data_pagamento`.
    """
    params_modelo: list[Any] = []
    filtro_modelo_receita = ""
    if modelo_ids:
        filtro_modelo_receita = "AND a.modelo_id = ANY(%s)"
        params_modelo.append(modelo_ids)

    filtro_modelo_repasse = ""
    if modelo_ids:
        filtro_modelo_repasse = "AND modelo_id = ANY(%s)"

    sql = f"""
        WITH receita AS (
          SELECT
            COUNT(DISTINCT a.id)::int AS contagem,
            COALESCE(SUM(a.valor_final), 0)::numeric AS valor_bruto,
            COALESCE(SUM(
              a.valor_final * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
            ), 0)::numeric AS valor_liquido,
            COALESCE(SUM(
              a.valor_final * COALESCE(a.percentual_repasse_snapshot, 0) / 100
            ), 0)::numeric AS valor_repasse,
            COALESCE(SUM(a.valor_final) FILTER (
              WHERE a.percentual_repasse_snapshot IS NULL
            ), 0)::numeric AS valor_sem_repasse_definido,
            COUNT(DISTINCT a.id) FILTER (
              WHERE a.percentual_repasse_snapshot IS NULL
            )::int AS contagem_sem_snapshot
            FROM barravips.atendimentos a
            JOIN barravips.eventos e ON e.atendimento_id = a.id
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             AND e.created_at >= %s AND e.created_at <= %s
             {filtro_modelo_receita}
        ),
        pago AS (
          SELECT COALESCE(SUM(valor), 0)::numeric AS total
            FROM barravips.financeiro_repasses_pagos
           WHERE data_pagamento >= %s::date
             AND data_pagamento <= %s::date
             {filtro_modelo_repasse}
        )
        SELECT receita.*, pago.total AS pago_total
          FROM receita, pago
    """

    # Ordem dos placeholders: receita(2 datas + modelo?), pago(2 datas + modelo?).
    params: list[Any] = [janela.inicio, janela.fim, *params_modelo,
                         janela.de, janela.ate]
    if modelo_ids:
        params.append(modelo_ids)

    result = await conn.execute(sql, params)
    row = await result.fetchone()
    assert row is not None  # CTE sempre retorna 1 linha

    bruto = float(row["valor_bruto"])
    liquido = float(row["valor_liquido"])
    repasse_calc = float(row["valor_repasse"])
    repasse_pago = float(row["pago_total"])

    return FinanceiroResumo(
        valor_bruto_brl=round(bruto, 2),
        valor_liquido_brl=round(liquido, 2),  # liquido da agencia = bruto - repasse
        valor_repasse_calculado_brl=round(repasse_calc, 2),
        valor_sem_repasse_definido_brl=round(float(row["valor_sem_repasse_definido"]), 2),
        valor_repasse_pago_brl=round(repasse_pago, 2),
        valor_saldo_repasse_brl=round(repasse_calc - repasse_pago, 2),
        fechamentos_total=int(row["contagem"]),
        fechamentos_sem_snapshot=int(row["contagem_sem_snapshot"]),
    )


# =============================================================================
# Receitas (projeção)
# =============================================================================


async def listar_receitas(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_ids: list[UUID] | None,
    forma_pagamento: str | None,
    limit: int,
    cursor: tuple[datetime, UUID] | None,
) -> tuple[list[ReceitaLinha], tuple[datetime, UUID] | None]:
    """Lista paginada (keyset por (eventos.created_at DESC, atendimentos.id DESC))."""
    params: list[Any] = [janela.inicio, janela.fim]
    filtros: list[str] = []
    if modelo_ids:
        filtros.append("a.modelo_id = ANY(%s)")
        params.append(modelo_ids)
    if forma_pagamento:
        filtros.append("a.forma_pagamento = %s")
        params.append(forma_pagamento)
    if cursor:
        ts, aid = cursor
        filtros.append("(e.created_at, a.id) < (%s, %s)")
        params.extend([ts, aid])

    filtro_sql = ""
    if filtros:
        filtro_sql = "AND " + " AND ".join(filtros)

    # +1 para detectar próximo cursor.
    params.append(limit + 1)

    sql = f"""
        SELECT
          a.id AS atendimento_id,
          a.numero_curto,
          e.created_at AS fechado_em,
          a.modelo_id, m.nome AS modelo_nome,
          a.cliente_id, c.nome AS cliente_nome,
          a.forma_pagamento::text AS forma_pagamento,
          a.valor_final,
          a.percentual_repasse_snapshot
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
          JOIN barravips.modelos m ON m.id = a.modelo_id
          JOIN barravips.clientes c ON c.id = a.cliente_id
         WHERE a.estado = 'Fechado'
           AND e.tipo = 'fechado_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           {filtro_sql}
         ORDER BY e.created_at DESC, a.id DESC
         LIMIT %s
    """
    result = await conn.execute(sql, params)
    rows = list(await result.fetchall())

    has_next = len(rows) > limit
    page = rows[:limit]
    next_cursor: tuple[datetime, UUID] | None = None
    if has_next:
        last = page[-1]
        next_cursor = (last["fechado_em"], last["atendimento_id"])

    items: list[ReceitaLinha] = []
    for row in page:
        bruto = float(row["valor_final"])
        pct = row["percentual_repasse_snapshot"]
        repasse = round(bruto * float(pct) / 100.0, 2) if pct is not None else 0.0
        items.append(
            ReceitaLinha(
                atendimento_id=row["atendimento_id"],
                numero_curto=int(row["numero_curto"]),
                fechado_em=row["fechado_em"].isoformat(),
                modelo_id=row["modelo_id"],
                modelo_nome=row["modelo_nome"],
                cliente_id=row["cliente_id"],
                cliente_nome=row["cliente_nome"],
                forma_pagamento=row["forma_pagamento"],
                valor_bruto=round(bruto, 2),
                percentual_repasse_snapshot=float(pct) if pct is not None else None,
                valor_repasse_calculado=repasse,
            )
        )
    return items, next_cursor


# =============================================================================
# Contexto da receita (inspector lateral)
# =============================================================================


async def obter_contexto_receita(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    janela: Janela,
) -> ReceitaContextoResponse | None:
    """Contexto agregado da linha de receita: cliente cross-modelo + modelo.

    Cliente: agregados cross-modelo de todos os atendimentos `Fechado` (LTV).
    Modelo: posição no período do filtro + série diária dos últimos 30 dias
    absolutos (referência fixa, independente do filtro — sparkline estável).
    """
    # 1) Resolve cliente_id e modelo_id do atendimento.
    result = await conn.execute(
        """
        SELECT a.cliente_id, a.modelo_id, c.nome AS cliente_nome, m.nome AS modelo_nome
          FROM barravips.atendimentos a
          JOIN barravips.clientes c ON c.id = a.cliente_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    head = await result.fetchone()
    if head is None:
        return None

    cliente_id: UUID = head["cliente_id"]
    modelo_id: UUID = head["modelo_id"]

    # 2) Cliente cross-modelo (mesma lógica de `dominio/clientes/routes.py:69-83`).
    cli_result = await conn.execute(
        """
        SELECT
          COUNT(*)::int AS total_atendimentos,
          COUNT(*) FILTER (WHERE a.estado = 'Fechado')::int AS total_fechados,
          COALESCE(
            SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0
          )::numeric AS valor_total,
          MAX(a.updated_at) AS ultima_atividade,
          COUNT(DISTINCT a.modelo_id)::int AS modelos_distintas
          FROM barravips.atendimentos a
         WHERE a.cliente_id = %s
        """,
        (cliente_id,),
    )
    cli_row = await cli_result.fetchone()
    assert cli_row is not None

    cliente = ContextoCliente(
        cliente_id=cliente_id,
        nome=head["cliente_nome"],
        total_atendimentos=int(cli_row["total_atendimentos"]),
        total_fechados=int(cli_row["total_fechados"]),
        valor_total_brl=round(float(cli_row["valor_total"]), 2),
        ultima_atividade_iso=(
            cli_row["ultima_atividade"].isoformat()
            if cli_row["ultima_atividade"] is not None
            else None
        ),
        modelos_distintas=int(cli_row["modelos_distintas"]),
    )

    # 3) Modelo no período (mesma fórmula do resumo) — agregado para a janela.
    mod_periodo_result = await conn.execute(
        """
        SELECT
          COUNT(DISTINCT a.id)::int AS fechamentos,
          COALESCE(SUM(a.valor_final), 0)::numeric AS bruto,
          COALESCE(SUM(
            a.valor_final * COALESCE(a.percentual_repasse_snapshot, 0) / 100
          ), 0)::numeric AS repasse
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
         WHERE a.estado = 'Fechado'
           AND e.tipo = 'fechado_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           AND a.modelo_id = %s
        """,
        (janela.inicio, janela.fim, modelo_id),
    )
    mod_periodo = await mod_periodo_result.fetchone()
    assert mod_periodo is not None

    # 4) Série diária dos últimos 30 dias absolutos (sparkline estável).
    # AT TIME ZONE 'America/Sao_Paulo' para alinhar agregação com BRT.
    serie_result = await conn.execute(
        """
        WITH dias AS (
          SELECT generate_series(
            (CURRENT_DATE - INTERVAL '29 days')::date,
            CURRENT_DATE::date,
            INTERVAL '1 day'
          )::date AS dia
        ),
        receitas_dia AS (
          SELECT
            (e.created_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
            SUM(a.valor_final)::numeric AS bruto
            FROM barravips.atendimentos a
            JOIN barravips.eventos e ON e.atendimento_id = a.id
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             AND a.modelo_id = %s
             AND e.created_at >= (CURRENT_DATE - INTERVAL '29 days')::timestamptz
           GROUP BY 1
        )
        SELECT dias.dia,
               COALESCE(receitas_dia.bruto, 0)::numeric AS bruto
          FROM dias
          LEFT JOIN receitas_dia ON receitas_dia.dia = dias.dia
         ORDER BY dias.dia ASC
        """,
        (modelo_id,),
    )
    serie_rows = list(await serie_result.fetchall())
    serie = [
        ContextoModeloDia(
            dia=row["dia"].isoformat(),
            bruto=round(float(row["bruto"]), 2),
        )
        for row in serie_rows
    ]

    modelo = ContextoModelo(
        modelo_id=modelo_id,
        nome=head["modelo_nome"],
        fechamentos_periodo=int(mod_periodo["fechamentos"]),
        valor_bruto_periodo=round(float(mod_periodo["bruto"]), 2),
        valor_repasse_periodo=round(float(mod_periodo["repasse"]), 2),
        serie_30d=serie,
    )

    return ReceitaContextoResponse(
        atendimento_id=atendimento_id,
        cliente=cliente,
        modelo=modelo,
    )


# =============================================================================
# Repasses pagos
# =============================================================================


async def listar_pagamentos(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_ids: list[UUID] | None,
    limit: int,
    cursor: tuple[date, UUID] | None,
) -> tuple[list[RepassePagoResponse], tuple[date, UUID] | None]:
    params: list[Any] = [janela.de, janela.ate]
    filtros: list[str] = []
    if modelo_ids:
        filtros.append("p.modelo_id = ANY(%s)")
        params.append(modelo_ids)
    if cursor:
        d, pid = cursor
        filtros.append("(p.data_pagamento, p.id) < (%s, %s)")
        params.extend([d, pid])

    filtro_sql = ""
    if filtros:
        filtro_sql = "AND " + " AND ".join(filtros)

    params.append(limit + 1)

    result = await conn.execute(
        f"""
        SELECT
          p.id, p.modelo_id, m.nome AS modelo_nome,
          p.data_pagamento, p.valor, p.forma_pagamento::text AS forma_pagamento,
          p.observacao, p.comprovante_object_key,
          p.created_at, p.updated_at
          FROM barravips.financeiro_repasses_pagos p
          JOIN barravips.modelos m ON m.id = p.modelo_id
         WHERE p.data_pagamento >= %s::date AND p.data_pagamento <= %s::date
           {filtro_sql}
         ORDER BY p.data_pagamento DESC, p.id DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())

    has_next = len(rows) > limit
    page = rows[:limit]
    next_cursor: tuple[date, UUID] | None = None
    if has_next:
        last = page[-1]
        next_cursor = (last["data_pagamento"], last["id"])

    items = [
        RepassePagoResponse(
            id=row["id"],
            modelo_id=row["modelo_id"],
            modelo_nome=row["modelo_nome"],
            data_pagamento=row["data_pagamento"],
            valor=Decimal(str(row["valor"])),
            forma_pagamento=row["forma_pagamento"],
            observacao=row["observacao"],
            comprovante_object_key=row["comprovante_object_key"],
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )
        for row in page
    ]
    return items, next_cursor


async def criar_pagamento(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    data_pagamento: date,
    valor: Decimal,
    forma_pagamento: str,
    observacao: str | None,
    comprovante_object_key: str | None,
    user_id: UUID,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.financeiro_repasses_pagos
            (modelo_id, data_pagamento, valor, forma_pagamento,
             observacao, comprovante_object_key, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (modelo_id, data_pagamento, valor, forma_pagamento,
         observacao, comprovante_object_key, user_id),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar_pagamento(
    conn: AsyncConnection[Any],
    pagamento_id: UUID,
    *,
    data_pagamento: date | None,
    valor: Decimal | None,
    forma_pagamento: str | None,
    observacao: str | None,
    comprovante_object_key: str | None,
) -> bool:
    sets: list[str] = []
    params: list[Any] = []
    if data_pagamento is not None:
        sets.append("data_pagamento = %s")
        params.append(data_pagamento)
    if valor is not None:
        sets.append("valor = %s")
        params.append(valor)
    if forma_pagamento is not None:
        sets.append("forma_pagamento = %s")
        params.append(forma_pagamento)
    if observacao is not None:
        sets.append("observacao = %s")
        params.append(observacao)
    if comprovante_object_key is not None:
        sets.append("comprovante_object_key = %s")
        params.append(comprovante_object_key)
    if not sets:
        return True
    params.append(pagamento_id)
    result = await conn.execute(
        f"UPDATE barravips.financeiro_repasses_pagos SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0


async def excluir_pagamento(conn: AsyncConnection[Any], pagamento_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM barravips.financeiro_repasses_pagos WHERE id = %s",
        (pagamento_id,),
    )
    return result.rowcount > 0


async def obter_pagamento(
    conn: AsyncConnection[Any], pagamento_id: UUID
) -> RepassePagoResponse | None:
    result = await conn.execute(
        """
        SELECT
          p.id, p.modelo_id, m.nome AS modelo_nome,
          p.data_pagamento, p.valor, p.forma_pagamento::text AS forma_pagamento,
          p.observacao, p.comprovante_object_key,
          p.created_at, p.updated_at
          FROM barravips.financeiro_repasses_pagos p
          JOIN barravips.modelos m ON m.id = p.modelo_id
         WHERE p.id = %s
        """,
        (pagamento_id,),
    )
    row = await result.fetchone()
    if row is None:
        return None
    return RepassePagoResponse(
        id=row["id"],
        modelo_id=row["modelo_id"],
        modelo_nome=row["modelo_nome"],
        data_pagamento=row["data_pagamento"],
        valor=Decimal(str(row["valor"])),
        forma_pagamento=row["forma_pagamento"],
        observacao=row["observacao"],
        comprovante_object_key=row["comprovante_object_key"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


# =============================================================================
# Saldo por modelo (visão Repasses)
# =============================================================================


async def repasse_por_modelo(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_ids: list[UUID] | None,
) -> list[SaldoModelo]:
    """3 CTEs: calculado + pago + sem_snapshot, joined em `modelos`.

    LEFT JOIN com `modelos` para incluir modelos sem fechamento no período
    quando a lista filtrada inclui essas modelos. Sem filtro de modelo: lista
    apenas modelos com atendimento OU pagamento no período (não retorna toda
    a base).
    """
    params_modelo_fech: list[Any] = []
    filtro_fech = ""
    if modelo_ids:
        filtro_fech = "AND a.modelo_id = ANY(%s)"
        params_modelo_fech.append(modelo_ids)

    params_modelo_pago: list[Any] = []
    filtro_pago = ""
    if modelo_ids:
        filtro_pago = "AND modelo_id = ANY(%s)"
        params_modelo_pago.append(modelo_ids)

    # Filtro final no LEFT JOIN: se modelo_ids informado, restringe; senão,
    # retorna apenas modelos com algum sinal no período.
    filtro_modelo_final = ""
    params_modelo_final: list[Any] = []
    if modelo_ids:
        filtro_modelo_final = "WHERE m.id = ANY(%s)"
        params_modelo_final.append(modelo_ids)
    else:
        filtro_modelo_final = "WHERE c.modelo_id IS NOT NULL OR p.modelo_id IS NOT NULL"

    sql = f"""
        WITH calc AS (
          SELECT a.modelo_id,
                 COUNT(DISTINCT a.id)::int AS contagem,
                 COALESCE(SUM(a.valor_final), 0)::numeric AS bruto,
                 COALESCE(SUM(
                   a.valor_final * COALESCE(a.percentual_repasse_snapshot, 0) / 100
                 ), 0)::numeric AS repasse_calc,
                 COUNT(DISTINCT a.id) FILTER (
                   WHERE a.percentual_repasse_snapshot IS NULL
                 )::int AS sem_snapshot_count,
                 COALESCE(SUM(a.valor_final) FILTER (
                   WHERE a.percentual_repasse_snapshot IS NULL
                 ), 0)::numeric AS sem_snapshot_valor
            FROM barravips.atendimentos a
            JOIN barravips.eventos e ON e.atendimento_id = a.id
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             AND e.created_at >= %s AND e.created_at <= %s
             {filtro_fech}
           GROUP BY a.modelo_id
        ),
        pago AS (
          SELECT modelo_id, COALESCE(SUM(valor), 0)::numeric AS total
            FROM barravips.financeiro_repasses_pagos
           WHERE data_pagamento >= %s::date AND data_pagamento <= %s::date
             {filtro_pago}
           GROUP BY modelo_id
        )
        SELECT
          m.id AS modelo_id,
          m.nome AS modelo_nome,
          COALESCE(c.contagem, 0)::int AS contagem,
          COALESCE(c.bruto, 0)::numeric AS bruto,
          COALESCE(c.repasse_calc, 0)::numeric AS repasse_calc,
          COALESCE(p.total, 0)::numeric AS repasse_pago,
          COALESCE(c.sem_snapshot_count, 0)::int AS sem_snapshot_count,
          COALESCE(c.sem_snapshot_valor, 0)::numeric AS sem_snapshot_valor
          FROM barravips.modelos m
          LEFT JOIN calc c ON c.modelo_id = m.id
          LEFT JOIN pago p ON p.modelo_id = m.id
          {filtro_modelo_final}
         ORDER BY (COALESCE(c.repasse_calc, 0) - COALESCE(p.total, 0)) DESC,
                  m.nome ASC
    """

    params = [
        janela.inicio, janela.fim, *params_modelo_fech,
        janela.de, janela.ate, *params_modelo_pago,
        *params_modelo_final,
    ]
    result = await conn.execute(sql, params)
    rows = list(await result.fetchall())

    return [
        SaldoModelo(
            modelo_id=row["modelo_id"],
            modelo_nome=row["modelo_nome"],
            fechamentos_total=int(row["contagem"]),
            valor_bruto=round(float(row["bruto"]), 2),
            valor_repasse_calculado=round(float(row["repasse_calc"]), 2),
            valor_repasse_pago=round(float(row["repasse_pago"]), 2),
            saldo=round(float(row["repasse_calc"]) - float(row["repasse_pago"]), 2),
            fechamentos_sem_snapshot=int(row["sem_snapshot_count"]),
            valor_sem_snapshot=round(float(row["sem_snapshot_valor"]), 2),
        )
        for row in rows
    ]


# =============================================================================
# Atendimentos sem snapshot (para botão "Preencher retroativo")
# =============================================================================


async def listar_atendimentos_sem_snapshot(
    conn: AsyncConnection[Any],
    modelo_id: UUID,
) -> list[AtendimentoSemSnapshotLinha]:
    result = await conn.execute(
        """
        SELECT
          a.id AS atendimento_id,
          a.numero_curto,
          e.created_at AS fechado_em,
          c.nome AS cliente_nome,
          a.valor_final
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
          JOIN barravips.clientes c ON c.id = a.cliente_id
         WHERE a.estado = 'Fechado'
           AND a.percentual_repasse_snapshot IS NULL
           AND a.modelo_id = %s
           AND e.tipo = 'fechado_registrado'
         ORDER BY e.created_at DESC
        """,
        (modelo_id,),
    )
    rows = list(await result.fetchall())
    return [
        AtendimentoSemSnapshotLinha(
            atendimento_id=row["atendimento_id"],
            numero_curto=int(row["numero_curto"]),
            fechado_em=row["fechado_em"].isoformat(),
            cliente_nome=row["cliente_nome"],
            valor_bruto=round(float(row["valor_final"]), 2),
        )
        for row in rows
    ]


async def preencher_repasse_retroativo(
    conn: AsyncConnection[Any],
    atendimento_ids: list[UUID],
    percentual: Decimal,
    user_id: UUID,
) -> int:
    """UPDATE em massa + 1 evento `correcao_registro` por atendimento.

    Filtra por `percentual_repasse_snapshot IS NULL AND estado='Fechado'` —
    nunca sobrescreve um snapshot já definido. Retorna a contagem real.
    """
    result = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET percentual_repasse_snapshot = %s
         WHERE id = ANY(%s)
           AND percentual_repasse_snapshot IS NULL
           AND estado = 'Fechado'
        RETURNING id
        """,
        (percentual, atendimento_ids),
    )
    atualizados = list(await result.fetchall())

    if atualizados:
        payload = {
            "campo": "percentual_repasse_snapshot",
            "valor": str(percentual),
            "origem": "financeiro_retroativo",
        }
        payload_json = json.dumps(payload, default=str)
        for row in atualizados:
            await conn.execute(
                """
                INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
                VALUES (%s, 'correcao_registro', 'painel', 'Fernando', %s::jsonb)
                """,
                (row["id"], payload_json),
            )

    return len(atualizados)
