"""SQL puro psycopg3 do Módulo Financeiro (ADR 0011 / 0002).

Receita = projeção sobre `barravips.atendimentos` JOIN `barravips.eventos`
(tipo='fechado_registrado'). Despesas e repasses têm tabelas próprias.
Fórmulas de líquido/repasse são as MESMAS do `dashboard/routes.py:_fechamentos`
e `painel/routes.py:198-217` — manter sincronizadas, divergir = bug.
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
    DespesaLinha,
    DespesaRecorrenteResponse,
    FinanceiroResumo,
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
    """Agregado da janela: bruto, líquido, repasse calc/pago/saldo, despesas.

    Receita filtra por evento `fechado_registrado.created_at` (regime caixa,
    ADR 0011). Despesa filtra por `COALESCE(competencia_mes, data)` cobrindo
    pontuais + materializadas. Pagamentos filtram por `data_pagamento`.

    NÃO inclui projeções de recorrentes (templates ainda não materializadas)
    no agregado por design: agregar projeção mistura dado real com previsão.
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
        despesa AS (
          SELECT COALESCE(SUM(valor), 0)::numeric AS total
            FROM barravips.financeiro_despesas
           WHERE COALESCE(competencia_mes, data) >= %s::date
             AND COALESCE(competencia_mes, data) <= %s::date
        ),
        pago AS (
          SELECT COALESCE(SUM(valor), 0)::numeric AS total
            FROM barravips.financeiro_repasses_pagos
           WHERE data_pagamento >= %s::date
             AND data_pagamento <= %s::date
             {filtro_modelo_repasse}
        )
        SELECT receita.*, despesa.total AS despesa_total, pago.total AS pago_total
          FROM receita, despesa, pago
    """

    # Ordem dos placeholders: receita(2 datas + modelo?), despesa(2 datas),
    # pago(2 datas + modelo?). Modelo no filtro_modelo_receita e _repasse.
    params: list[Any] = [janela.inicio, janela.fim, *params_modelo,
                         janela.de, janela.ate,
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
    despesas = float(row["despesa_total"])

    return FinanceiroResumo(
        valor_bruto_brl=round(bruto, 2),
        valor_liquido_brl=round(liquido - despesas, 2),  # liquido da agencia = bruto - repasse - despesa
        valor_repasse_calculado_brl=round(repasse_calc, 2),
        valor_sem_repasse_definido_brl=round(float(row["valor_sem_repasse_definido"]), 2),
        valor_repasse_pago_brl=round(repasse_pago, 2),
        valor_saldo_repasse_brl=round(repasse_calc - repasse_pago, 2),
        valor_despesas_brl=round(despesas, 2),
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
# Despesas
# =============================================================================


async def listar_despesas(
    conn: AsyncConnection[Any],
    janela: Janela,
    categorias: list[str] | None,
) -> list[DespesaLinha]:
    """UNION ALL: pontuais + materializadas + projeções de templates ativos.

    Projeções derivam de templates ativos no período, anti-join com instâncias
    já materializadas. Sem cursor: lista de despesa por janela é pequena.
    """
    filtro_cat = ""
    if categorias:
        filtro_cat = "AND categoria = ANY(%s)"

    params: list[Any] = [janela.de, janela.ate]
    if categorias:
        params.append(categorias)

    sql_pontuais = f"""
        SELECT
          id, categoria::text AS categoria, valor, data, descricao,
          recorrente_id, competencia_mes,
          CASE WHEN recorrente_id IS NULL THEN 'pontual'
               ELSE 'recorrente_materializada' END AS origem,
          NULL::numeric AS valor_template
          FROM barravips.financeiro_despesas
         WHERE COALESCE(competencia_mes, data) >= %s::date
           AND COALESCE(competencia_mes, data) <= %s::date
           {filtro_cat}
    """

    # Projeções: para cada mês da janela, para cada template ativo nesse mês
    # que não tem materialização, gerar uma linha sintética.
    params_proj: list[Any] = [janela.de, janela.ate]
    filtro_cat_proj = ""
    if categorias:
        filtro_cat_proj = "AND r.categoria = ANY(%s)"
        params_proj.append(categorias)

    sql_projetadas = f"""
        SELECT
          NULL::uuid AS id,
          r.categoria::text AS categoria,
          r.valor,
          -- data sintética: 1º do mês (alinhado a competencia_mes)
          (mes_ref::date + (LEAST(r.dia_do_mes, 28) - 1) * INTERVAL '1 day')::date AS data,
          r.descricao,
          r.id AS recorrente_id,
          mes_ref::date AS competencia_mes,
          'recorrente_projetada' AS origem,
          r.valor AS valor_template
          FROM generate_series(
            date_trunc('month', %s::date),
            date_trunc('month', %s::date),
            INTERVAL '1 month'
          ) AS mes_ref
          JOIN barravips.financeiro_despesas_recorrentes r
            ON r.ativo_desde <= mes_ref::date
           AND (r.inativo_em IS NULL OR r.inativo_em > mes_ref::date)
         WHERE NOT EXISTS (
           SELECT 1 FROM barravips.financeiro_despesas d
            WHERE d.recorrente_id = r.id
              AND d.competencia_mes = mes_ref::date
         )
         {filtro_cat_proj}
    """

    sql = f"""
        ({sql_pontuais})
        UNION ALL
        ({sql_projetadas})
        ORDER BY data DESC
    """

    result = await conn.execute(sql, [*params, *params_proj])
    rows = list(await result.fetchall())

    items: list[DespesaLinha] = []
    for row in rows:
        items.append(
            DespesaLinha(
                id=row["id"],
                categoria=row["categoria"],
                valor=Decimal(str(row["valor"])),
                data=row["data"],
                descricao=row["descricao"],
                recorrente_id=row["recorrente_id"],
                competencia_mes=row["competencia_mes"],
                origem=row["origem"],
                valor_template=(Decimal(str(row["valor_template"]))
                                if row["valor_template"] is not None else None),
            )
        )
    return items


async def criar_despesa_pontual(
    conn: AsyncConnection[Any],
    *,
    categoria: str,
    valor: Decimal,
    data: date,
    descricao: str | None,
    user_id: UUID,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.financeiro_despesas
            (categoria, valor, data, descricao, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (categoria, valor, data, descricao, user_id),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar_despesa(
    conn: AsyncConnection[Any],
    despesa_id: UUID,
    *,
    categoria: str | None,
    valor: Decimal | None,
    data: date | None,
    descricao: str | None,
) -> bool:
    sets: list[str] = []
    params: list[Any] = []
    if categoria is not None:
        sets.append("categoria = %s")
        params.append(categoria)
    if valor is not None:
        sets.append("valor = %s")
        params.append(valor)
    if data is not None:
        sets.append("data = %s")
        params.append(data)
    if descricao is not None:
        sets.append("descricao = %s")
        params.append(descricao)
    if not sets:
        return True
    params.append(despesa_id)
    result = await conn.execute(
        f"UPDATE barravips.financeiro_despesas SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0


async def excluir_despesa(conn: AsyncConnection[Any], despesa_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM barravips.financeiro_despesas WHERE id = %s",
        (despesa_id,),
    )
    return result.rowcount > 0


async def materializar_recorrente(
    conn: AsyncConnection[Any],
    *,
    recorrente_id: UUID,
    competencia_mes: date,
    user_id: UUID,
) -> UUID:
    """Copia categoria/valor/descrição do template e insere linha real.

    UNIQUE parcial em `(recorrente_id, competencia_mes) WHERE recorrente_id IS NOT NULL`
    impede duplicação — repetir a chamada retorna o id existente.
    """
    # Tenta inserir; se conflitar, retorna o id existente.
    result = await conn.execute(
        """
        WITH tpl AS (
          SELECT categoria, valor, descricao,
                 (%s::date + (LEAST(dia_do_mes, 28) - 1) * INTERVAL '1 day')::date AS data_lancamento
            FROM barravips.financeiro_despesas_recorrentes
           WHERE id = %s
        ),
        novo AS (
          INSERT INTO barravips.financeiro_despesas
            (categoria, valor, data, descricao, recorrente_id, competencia_mes, created_by)
          SELECT categoria, valor, data_lancamento, descricao, %s, %s, %s
            FROM tpl
          ON CONFLICT (recorrente_id, competencia_mes)
            WHERE recorrente_id IS NOT NULL DO NOTHING
          RETURNING id
        )
        SELECT id FROM novo
        UNION ALL
        SELECT id FROM barravips.financeiro_despesas
         WHERE recorrente_id = %s AND competencia_mes = %s
        LIMIT 1
        """,
        (competencia_mes, recorrente_id, recorrente_id, competencia_mes, user_id,
         recorrente_id, competencia_mes),
    )
    row = await result.fetchone()
    if row is None:
        # Template não existe.
        raise ValueError("recorrente nao encontrada")
    return UUID(str(row["id"]))


# =============================================================================
# Despesas recorrentes (templates)
# =============================================================================


async def listar_recorrentes(
    conn: AsyncConnection[Any],
    incluir_inativas: bool,
) -> list[DespesaRecorrenteResponse]:
    filtro = "" if incluir_inativas else "WHERE inativo_em IS NULL"
    result = await conn.execute(
        f"""
        SELECT id, categoria::text AS categoria, valor, descricao, dia_do_mes,
               ativo_desde, inativo_em, created_at, updated_at
          FROM barravips.financeiro_despesas_recorrentes
          {filtro}
         ORDER BY inativo_em IS NULL DESC, descricao ASC
        """
    )
    rows = list(await result.fetchall())
    return [
        DespesaRecorrenteResponse(
            id=row["id"],
            categoria=row["categoria"],
            valor=Decimal(str(row["valor"])),
            descricao=row["descricao"],
            dia_do_mes=int(row["dia_do_mes"]),
            ativo_desde=row["ativo_desde"],
            inativo_em=row["inativo_em"],
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )
        for row in rows
    ]


async def criar_recorrente(
    conn: AsyncConnection[Any],
    *,
    categoria: str,
    valor: Decimal,
    descricao: str,
    dia_do_mes: int,
    ativo_desde: date,
    user_id: UUID,
) -> UUID:
    result = await conn.execute(
        """
        INSERT INTO barravips.financeiro_despesas_recorrentes
            (categoria, valor, descricao, dia_do_mes, ativo_desde, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (categoria, valor, descricao, dia_do_mes, ativo_desde, user_id),
    )
    row = await result.fetchone()
    assert row is not None
    return UUID(str(row["id"]))


async def atualizar_recorrente(
    conn: AsyncConnection[Any],
    recorrente_id: UUID,
    *,
    categoria: str | None,
    valor: Decimal | None,
    descricao: str | None,
    dia_do_mes: int | None,
) -> bool:
    sets: list[str] = []
    params: list[Any] = []
    if categoria is not None:
        sets.append("categoria = %s")
        params.append(categoria)
    if valor is not None:
        sets.append("valor = %s")
        params.append(valor)
    if descricao is not None:
        sets.append("descricao = %s")
        params.append(descricao)
    if dia_do_mes is not None:
        sets.append("dia_do_mes = %s")
        params.append(dia_do_mes)
    if not sets:
        return True
    params.append(recorrente_id)
    result = await conn.execute(
        f"UPDATE barravips.financeiro_despesas_recorrentes SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return result.rowcount > 0


async def desativar_recorrente(
    conn: AsyncConnection[Any],
    recorrente_id: UUID,
    inativo_em: date,
) -> bool:
    result = await conn.execute(
        """
        UPDATE barravips.financeiro_despesas_recorrentes
           SET inativo_em = %s
         WHERE id = %s
        """,
        (inativo_em, recorrente_id),
    )
    return result.rowcount > 0


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
