"""Endpoints agregados para a Tela 07 (Dashboard)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import EntradaInvalida
from barra.core.janela import (
    BRT,
    Janela,
)
from barra.core.janela import (
    filtro_aplicado_dict as _filtro_aplicado_dict,
)
from barra.core.janela import (
    janela_anterior as _janela_anterior,
)
from barra.core.janela import (
    piso_operacao as _piso_operacao,
)
from barra.core.janela import (
    resolver_janela as _resolver_janela,
)
from barra.dominio.escaladas.modelos import TipoEscalada, rotulo_tipo_escalada
from barra.dominio.financeiro.calculos import VALOR_SERVICO_SQL as _VS
from barra.dominio.financeiro.repo import importados_sem_data as _importados_sem_data

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("")
async def dashboard(
    periodo: Literal["hoje", "7d", "30d", "mes", "tudo", "custom"] = "7d",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    piso = await _piso_tudo(conn, modelo_id) if periodo == "tudo" else None
    janela = _resolver_janela(periodo, de, ate, piso_tudo=piso)
    # "tudo" abrange toda a operação — comparação com período anterior não faz sentido.
    janela_anterior = _janela_anterior(janela) if periodo != "tudo" else None

    pix_pendentes = await _pix_pendentes_total(conn, modelo_id)
    kpis_periodo = await _kpis(conn, janela, modelo_id)
    kpis_anterior = await _kpis(conn, janela_anterior, modelo_id) if janela_anterior else None
    funil = await _funil_coorte(conn, janela, modelo_id)
    norte = await _norte_cotacao(conn, janela, modelo_id)
    perdas = await _perdas_por_motivo(conn, janela, modelo_id)
    escalada_top = await _motivos_escalada_top(conn, janela, modelo_id)
    profissionais = await _profissionais(conn, janela)
    roi = await _roi(conn, janela, modelo_id)
    # Fechados importados sem evento `fechado_registrado` (sem data — ex.: histórico do
    # caderno do vendedor). O regime caixa (ADR 0011) ancora receita no evento, então eles
    # ficam FORA de todo recorte por período acima. Espelhamos o balde do Financeiro
    # (financeiro/repo.importados_sem_data) para não somirem do dashboard.
    imp_contagem, imp_bruto = await _importados_sem_data(conn, modelo_id)

    agora = datetime.now(BRT)

    return {
        "filtro_aplicado": _filtro_aplicado_dict(periodo, janela, modelo_id),
        "janela_comparacao": (
            {"de": janela_anterior.de.isoformat(), "ate": janela_anterior.ate.isoformat()}
            if janela_anterior
            else None
        ),
        "pix_em_revisao_pendentes_total": pix_pendentes,
        "kpis_periodo": kpis_periodo,
        "kpis_periodo_anterior": kpis_anterior,
        "financeiro": _financeiro_bloco(kpis_periodo),
        "financeiro_periodo_anterior": (
            _financeiro_bloco(kpis_anterior) if kpis_anterior else None
        ),
        "funil": funil,
        "norte_cotacao": norte,
        "perdas_por_motivo": perdas,
        "motivos_escalada": escalada_top,
        "profissionais": profissionais,
        "roi_ia": roi,
        "importados_sem_data": {"contagem": imp_contagem, "valor_bruto_brl": imp_bruto},
        "servidor_em": agora.isoformat(),
    }


def _financeiro_bloco(kpis: dict[str, Any]) -> dict[str, Any]:
    """Bloco financeiro top-level — reutiliza o dict ``fechamentos`` já calculado em ``_kpis``."""
    f = kpis["fechamentos"]
    return {
        "valor_bruto_brl": f["valor_bruto_brl"],
        "valor_liquido_brl": f["valor_liquido_brl"],
        "valor_repasse_modelo_brl": f["valor_repasse_modelo_brl"],
        "valor_sem_repasse_definido_brl": f["valor_sem_repasse_definido_brl"],
        "fechamentos_total": f["contagem"],
        "fechamentos_sem_snapshot": f["contagem_sem_snapshot"],
    }


async def _piso_tudo(conn: AsyncConnection[Any], modelo_id: list[UUID] | None) -> date | None:
    """Borda esquerda do período "tudo": data do 1º atendimento da operação
    (escopado pelo filtro de modelo). Evita o vão vazio do antigo piso 2020."""
    filtro_modelo = ""
    params: list[Any] = []
    if modelo_id:
        filtro_modelo = "WHERE a.modelo_id = ANY(%s)"
        params.append(modelo_id)
    return await _piso_operacao(
        conn,
        f"SELECT MIN(a.created_at) FROM barravips.atendimentos a {filtro_modelo}",
        params,
    )


async def _roi(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    """Bloco ROI da IA (CUSTO-01 / ADR 0012): comissão paga a humanos vs comissão evitada pela IA.

    - `comissao_calculada_brl`: comissão projetada dos `Fechado` conduzidos por VENDEDOR humano
      (vendedor_id não nulo), pela alíquota do nível — o que a operação humana custa.
    - `comissao_evitada_brl`: dos `Fechado` conduzidos pela IA (vendedor_id NULL), o valor do
      serviço x alíquota de REFERÊNCIA (nível 'intermediario' da config) — a comissão que a IA
      poupa por conduzir sem vendedor.
    - `custo_ia_brl`: custo de CHAT (Sonnet) acumulado por turno em `atendimentos.custo_ia_brl`
      pelo coordenador (OBS go-live) — soma dos atendimentos CRIADOS na janela. STT/vision são
      marginais e seguem só no Prometheus (`agente_custo_{stt,vision}_brl`).
      `custo_ia_por_fechado` = custo_ia / fechados_ia (None sem fechados da IA).

    Base de comissão = valor do serviço (líquido de taxa, ADR 0013), via VALOR_SERVICO_SQL.
    Só `Fechado` conta. Espelha a âncora dedupada de `fechado_registrado`.
    """
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT
          COUNT(DISTINCT a.id) FILTER (WHERE a.vendedor_id IS NOT NULL)::int AS fechados_humano,
          COUNT(DISTINCT a.id) FILTER (WHERE a.vendedor_id IS NULL)::int AS fechados_ia,
          COALESCE(
            SUM({_VS} * cn.percentual / 100) FILTER (WHERE a.vendedor_id IS NOT NULL),
          0)::numeric AS comissao_calculada,
          COALESCE(
            SUM({_VS} * ref.percentual / 100) FILTER (WHERE a.vendedor_id IS NULL),
          0)::numeric AS comissao_evitada
          FROM barravips.atendimentos a
          JOIN LATERAL (
            SELECT created_at, tipo
              FROM barravips.eventos
             WHERE atendimento_id = a.id
               AND tipo = 'fechado_registrado'
             ORDER BY created_at DESC
             LIMIT 1
          ) e ON true
          LEFT JOIN barravips.vendedores ven ON ven.id = a.vendedor_id
          LEFT JOIN barravips.financeiro_comissao_niveis cn ON cn.nivel = ven.nivel
          -- alíquota de referência p/ a comissão evitada (IA não tem vendedor/nível).
          LEFT JOIN barravips.financeiro_comissao_niveis ref ON ref.nivel = 'intermediario'
         WHERE a.estado = 'Fechado'
           AND e.tipo = 'fechado_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    fechados_humano = int(row["fechados_humano"]) if row else 0
    fechados_ia = int(row["fechados_ia"]) if row else 0
    comissao_calculada = float(row["comissao_calculada"]) if row else 0.0
    comissao_evitada = float(row["comissao_evitada"]) if row else 0.0

    # Custo de chat acumulado nos atendimentos CRIADOS na janela (a coluna é por atendimento,
    # não por turno — a âncora natural é o created_at do atendimento).
    params_custo: list[Any] = [janela.inicio, janela.fim]
    filtro_custo = ""
    if modelo_id:
        filtro_custo = "AND a.modelo_id = ANY(%s)"
        params_custo.append(modelo_id)
    result_custo = await conn.execute(
        f"""
        SELECT COALESCE(SUM(a.custo_ia_brl), 0)::numeric AS custo_ia
          FROM barravips.atendimentos a
         WHERE a.created_at >= %s AND a.created_at <= %s
           {filtro_custo}
        """,
        params_custo,
    )
    row_custo = await result_custo.fetchone()
    custo_ia = float(row_custo["custo_ia"]) if row_custo else 0.0

    return {
        "fechados_humano": fechados_humano,
        "fechados_ia": fechados_ia,
        "comissao_calculada_brl": round(comissao_calculada, 2),
        "comissao_evitada_brl": round(comissao_evitada, 2),
        "custo_ia_brl": round(custo_ia, 2),
        "custo_ia_por_fechado_brl": (round(custo_ia / fechados_ia, 2) if fechados_ia else None),
        "nota_custo_ia": (
            "custo de chat (Sonnet) acumulado por turno pelo coordenador; estimativa, não fatura. "
            "STT/vision marginais seguem no Prometheus (agente_custo_{stt,vision}_brl)"
        ),
    }


@router.get("/escaladas")
async def dashboard_escaladas(
    periodo: Literal["hoje", "7d", "30d", "mes", "tudo", "custom"] = "7d",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    """Lista completa de escaladas (para dialog "ver todas")."""
    piso = await _piso_tudo(conn, modelo_id) if periodo == "tudo" else None
    janela = _resolver_janela(periodo, de, ate, piso_tudo=piso)

    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT e.tipo::text AS tipo,
               e.observacao AS observacao,
               e.motivo AS motivo,
               m.nome AS modelo_nome,
               COUNT(*)::int AS contagem
          FROM barravips.escaladas e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE e.aberta_em >= %s AND e.aberta_em <= %s {filtro_modelo}
         GROUP BY e.tipo, e.observacao, e.motivo, m.nome
         ORDER BY contagem DESC, tipo ASC
        """,
        params,
    )
    linhas: list[dict[str, Any]] = []
    for row in await result.fetchall():
        tipo_str = str(row["tipo"])
        rotulo = rotulo_tipo_escalada(TipoEscalada(tipo_str))
        linhas.append(
            {
                "tipo": tipo_str,
                "rotulo": rotulo,
                "observacao": row["observacao"],
                "motivo": row["motivo"],
                "modelo_nome": row["modelo_nome"],
                "contagem": int(row["contagem"]),
            }
        )

    return {
        "filtro_aplicado": _filtro_aplicado_dict(periodo, janela, modelo_id),
        "motivos": linhas,
    }


SERIE_METRICAS = ("conversao", "fechamentos", "perdas", "escaladas", "liquido", "bruto")
SERIE_UNIDADES = ("dia", "semana")
SERIE_N_MAX = 26
SERIE_N_MIN = 4


@router.get("/serie")
async def dashboard_serie(
    metrica: Literal[
        "conversao", "fechamentos", "perdas", "escaladas", "liquido", "bruto"
    ] = "conversao",
    unidade: Literal["dia", "semana"] = "semana",
    n: int = 12,
    modelo_id: Annotated[list[UUID] | None, Query()] = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    """Série temporal de uma métrica agregada por dia/semana — alimenta sparklines."""
    if metrica not in SERIE_METRICAS:
        raise EntradaInvalida("METRICA_INVALIDA", f"metrica desconhecida: {metrica}")
    if unidade not in SERIE_UNIDADES:
        raise EntradaInvalida("UNIDADE_INVALIDA", f"unidade desconhecida: {unidade}")
    if n < SERIE_N_MIN or n > SERIE_N_MAX:
        raise EntradaInvalida(
            "N_INVALIDO",
            f"n deve estar entre {SERIE_N_MIN} e {SERIE_N_MAX}",
        )

    pontos = await _serie(conn, metrica, unidade, n, modelo_id)
    return {
        "metrica": metrica,
        "unidade": unidade,
        "n": n,
        "modelo_ids": [str(m) for m in modelo_id] if modelo_id else [],
        "pontos": pontos,
    }


# Resolução de janela / filtro_aplicado vivem em barra.core.janela (compartilhado
# com o módulo Financeiro — ADR 0011). Importados via alias no topo deste arquivo
# para preservar os nomes _resolver_janela / _janela_anterior / _janela_de_datas /
# _filtro_aplicado_dict usados ao longo destes endpoints.


# -----------------------------------------------------------------------------
# Consultas
# -----------------------------------------------------------------------------


async def _pix_pendentes_total(conn: AsyncConnection[Any], modelo_id: list[UUID] | None) -> int:
    params: list[Any] = []
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = p.atendimento_id"
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT COUNT(*)::int AS n
          FROM barravips.comprovantes_pix p
          {join}
         WHERE p.decisao_pipeline = 'em_revisao'
           AND p.decisao_final IS NULL {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    return cast(int, row["n"]) if row else 0


async def _kpis(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    fechamentos = await _fechamentos(conn, janela, modelo_id)
    perdas = await _perdas(conn, janela, modelo_id)
    escaladas = await _escaladas_contagem(conn, janela, modelo_id)
    volume_periodo = await _volume_periodo(conn, janela, modelo_id)

    decididos = fechamentos["contagem"] + perdas["contagem"]
    taxa = (fechamentos["contagem"] / decididos * 100) if decididos > 0 else None

    return {
        "taxa_conversao_pct": round(taxa, 1) if taxa is not None else None,
        "n_decididos": decididos,
        "volume_periodo": volume_periodo,
        "fechamentos": {**fechamentos, "n_referencia": decididos},
        "perdas": {"contagem": perdas["contagem"], "n_referencia": decididos},
        "escaladas": {"contagem": escaladas, "n_referencia": volume_periodo},
    }


async def _volume_periodo(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> int:
    """Total de atendimentos criados na janela — denominador natural para % escalada."""
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND modelo_id = ANY(%s)"
        params.append(modelo_id)
    result = await conn.execute(
        f"""
        SELECT COUNT(*)::int AS n
          FROM barravips.atendimentos
         WHERE created_at >= %s AND created_at <= %s {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    return int(row["n"]) if row else 0


async def _fechamentos(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    # Fórmula espelhada em barra/dominio/painel/routes.py:198-217
    # Líquido (parcela da agência) = valor_final * (1 - COALESCE(pct, 0) / 100)
    # Repasse modelo             = valor_final *      COALESCE(pct, 0) / 100
    # Invariante: bruto == liquido + repasse_modelo. Quando pct IS NULL, o COALESCE
    # tratará como 0, então o valor inteiro vira líquido. `valor_sem_repasse_definido`
    # é informativo (soma dos fechados com pct NULL) para transparência no painel.
    result = await conn.execute(
        f"""
        SELECT
          COUNT(DISTINCT a.id)::int AS contagem,
          COALESCE(SUM(a.valor_final), 0)::numeric AS valor_bruto,
          COALESCE(SUM(
            (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
          ), 0)::numeric AS valor_liquido,
          COALESCE(SUM(
            (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * COALESCE(a.percentual_repasse_snapshot, 0) / 100
          ), 0)::numeric AS valor_repasse_modelo,
          COALESCE(SUM(a.valor_final) FILTER (
            WHERE a.percentual_repasse_snapshot IS NULL
          ), 0)::numeric AS valor_sem_repasse_definido,
          COUNT(DISTINCT a.id) FILTER (
            WHERE a.percentual_repasse_snapshot IS NULL
          )::int AS contagem_sem_snapshot
          FROM barravips.atendimentos a
          JOIN LATERAL (
            -- Ancora dedupada: 1 fechado_registrado por atendimento (o mais recente). Sem isso,
            -- atendimentos com 2+ eventos `fechado_registrado` (correcao Fechado->Perdido->Fechado
            -- em escaladas/service._corrigir_registro) gerariam N linhas e inflariam os SUM de valor;
            -- COUNT(DISTINCT a.id) mascarava (contagem certa, dinheiro inflado). Espelha o dedup do
            -- modulo financeiro (financeiro/repo.py) -> bloco do dashboard e tela do modulo mostram o
            -- MESMO numero (ADR 0011, nao-negociavel). `tipo` no SELECT mantem valido o filtro externo.
            SELECT created_at, tipo
              FROM barravips.eventos
             WHERE atendimento_id = a.id
               AND tipo = 'fechado_registrado'
             ORDER BY created_at DESC
             LIMIT 1
          ) e ON true
         WHERE a.estado = 'Fechado'
           AND e.tipo = 'fechado_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    contagem = int(row["contagem"]) if row else 0
    valor_bruto = float(row["valor_bruto"]) if row else 0.0
    valor_liquido = float(row["valor_liquido"]) if row else 0.0
    valor_repasse_modelo = float(row["valor_repasse_modelo"]) if row else 0.0
    valor_sem_repasse_definido = float(row["valor_sem_repasse_definido"]) if row else 0.0
    contagem_sem_snapshot = int(row["contagem_sem_snapshot"]) if row else 0
    valor_medio = (valor_bruto / contagem) if contagem > 0 else 0.0
    return {
        "contagem": contagem,
        "valor_bruto_brl": round(valor_bruto, 2),
        "valor_medio_brl": round(valor_medio, 2),
        "valor_liquido_brl": round(valor_liquido, 2),
        "valor_repasse_modelo_brl": round(valor_repasse_modelo, 2),
        "valor_sem_repasse_definido_brl": round(valor_sem_repasse_definido, 2),
        "contagem_sem_snapshot": contagem_sem_snapshot,
    }


async def _perdas(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT COUNT(DISTINCT a.id)::int AS contagem
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
         WHERE a.estado = 'Perdido'
           AND e.tipo = 'perdido_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    return {"contagem": int(row["contagem"]) if row else 0}


async def _escaladas_contagem(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> int:
    params: list[Any] = [janela.inicio, janela.fim]
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = e.atendimento_id"
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT COUNT(*)::int AS n
          FROM barravips.escaladas e
          {join}
         WHERE e.aberta_em >= %s AND e.aberta_em <= %s {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone()
    return int(row["n"]) if row else 0


async def _funil_coorte(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    """Funil de coorte: por atendimento criado na janela, conta até onde ele progrediu.

    Como a IA não emite ``transicao_estado`` no avanço, o rank máximo atingido é
    derivado do estado atual (não-Perdido) ou do estado de origem da transição
    ``→ Perdido`` (Perdido). As duas convenções de payload coexistem no código
    (``de``/``para`` e ``estado_anterior``/``estado_novo``), por isso o COALESCE.

    Ranks: Qualificando=1, Aguardando=2, Em atendimento=3, Fechado=4. Um Perdido
    nunca chega a 4 (perdeu antes de fechar); origem ausente cai em Qualificando.
    ``coorte(K) = nº com rank ≥ K``; ``perda(K) = nº de Perdidos cujo rank = K``.
    """
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        WITH base AS (
            SELECT a.id, a.estado::text AS estado
              FROM barravips.atendimentos a
             WHERE a.created_at >= %s AND a.created_at <= %s {filtro_modelo}
        ),
        origem_perda AS (
            SELECT DISTINCT ON (e.atendimento_id)
                   e.atendimento_id,
                   COALESCE(e.payload->>'de', e.payload->>'estado_anterior') AS de_estado
              FROM barravips.eventos e
              JOIN base b ON b.id = e.atendimento_id
             WHERE e.tipo = 'transicao_estado'
               AND COALESCE(e.payload->>'para', e.payload->>'estado_novo') = 'Perdido'
             ORDER BY e.atendimento_id, e.created_at DESC
        ),
        com_rank AS (
            SELECT
                b.estado,
                CASE
                    WHEN b.estado = 'Perdido' THEN
                        CASE op.de_estado
                            WHEN 'Aguardando_confirmacao' THEN 2
                            WHEN 'Confirmado' THEN 2
                            WHEN 'Em_execucao' THEN 3
                            WHEN 'Fechado' THEN 3
                            ELSE 1
                        END
                    WHEN b.estado IN ('Novo', 'Triagem', 'Qualificado') THEN 1
                    WHEN b.estado IN ('Aguardando_confirmacao', 'Confirmado') THEN 2
                    WHEN b.estado = 'Em_execucao' THEN 3
                    WHEN b.estado = 'Fechado' THEN 4
                    ELSE 1
                END AS rank_max
              FROM base b
              LEFT JOIN origem_perda op ON op.atendimento_id = b.id
        )
        SELECT
            COUNT(*)::int AS topo,
            COUNT(*) FILTER (WHERE rank_max >= 2)::int AS coorte_aguardando,
            COUNT(*) FILTER (WHERE rank_max >= 3)::int AS coorte_execucao,
            COUNT(*) FILTER (WHERE rank_max >= 4)::int AS coorte_fechado,
            COUNT(*) FILTER (WHERE estado = 'Perdido' AND rank_max = 1)::int AS perda_qualificando,
            COUNT(*) FILTER (WHERE estado = 'Perdido' AND rank_max = 2)::int AS perda_aguardando,
            COUNT(*) FILTER (WHERE estado = 'Perdido' AND rank_max = 3)::int AS perda_execucao
          FROM com_rank
        """,
        params,
    )
    row = await result.fetchone() or {}
    topo = int(row.get("topo", 0) or 0)
    perda_q = int(row.get("perda_qualificando", 0) or 0)
    perda_a = int(row.get("perda_aguardando", 0) or 0)
    perda_e = int(row.get("perda_execucao", 0) or 0)
    etapas = [
        {"id": "Qualificando", "coorte": topo, "perdas": perda_q},
        {
            "id": "Aguardando",
            "coorte": int(row.get("coorte_aguardando", 0) or 0),
            "perdas": perda_a,
        },
        {"id": "Em_execucao", "coorte": int(row.get("coorte_execucao", 0) or 0), "perdas": perda_e},
        {"id": "Fechado", "coorte": int(row.get("coorte_fechado", 0) or 0), "perdas": 0},
    ]
    return {"topo": topo, "etapas": etapas, "perdidos_total": perda_q + perda_a + perda_e}


async def _norte_cotacao(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    """Métrica de norte: das threads COTADAS na janela, quantas fecharam e quanto renderam por
    thread cotada (conversão cotada→Fechado% + R$/thread).

    Coorte ancorada em ``cotacao_enviada_em`` (carimbado quando a IA apresenta o preço, ADR 0022),
    não em ``created_at``: o denominador é "lead que recebeu cotação", o sinal mais limpo de
    intenção real. ``estado = 'Fechado'`` lê o desfecho atual (como o funil de coorte), então
    coortes recentes ainda têm atendimentos ``em_aberto`` que sub-contam a conversão até decidirem.
    ``valor_final`` é por-atendimento (1 linha), então a receita não precisa do dedup por evento
    de ``_fechamentos``. Só ``Fechado`` entra na receita.
    """
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT
          COUNT(*)::int AS cotadas,
          COUNT(*) FILTER (WHERE a.estado = 'Fechado')::int AS fechadas,
          COUNT(*) FILTER (WHERE a.estado NOT IN ('Fechado', 'Perdido'))::int AS em_aberto,
          COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0)::numeric AS receita_bruta
          FROM barravips.atendimentos a
         WHERE a.cotacao_enviada_em >= %s AND a.cotacao_enviada_em <= %s
           {filtro_modelo}
        """,
        params,
    )
    row = await result.fetchone() or {}
    cotadas = int(row.get("cotadas", 0) or 0)
    fechadas = int(row.get("fechadas", 0) or 0)
    em_aberto = int(row.get("em_aberto", 0) or 0)
    receita_bruta = float(row.get("receita_bruta", 0) or 0)
    return {
        "cotadas": cotadas,
        "fechadas": fechadas,
        "em_aberto": em_aberto,
        "conversao_cotada_para_fechado_pct": (
            round(fechadas / cotadas * 100, 1) if cotadas else None
        ),
        "receita_bruta_brl": round(receita_bruta, 2),
        "r_por_thread_cotada_brl": (round(receita_bruta / cotadas, 2) if cotadas else None),
        "nota": (
            "coorte ancorada em cotacao_enviada_em (lead que recebeu preço); estado=Fechado é o "
            "desfecho atual, então coortes recentes sub-contam a conversão enquanto há em_aberto"
        ),
    }


async def _perdas_por_motivo(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT a.motivo_perda::text AS motivo, COUNT(DISTINCT a.id)::int AS contagem
          FROM barravips.atendimentos a
          JOIN barravips.eventos e ON e.atendimento_id = a.id
         WHERE a.estado = 'Perdido'
           AND e.tipo = 'perdido_registrado'
           AND e.created_at >= %s AND e.created_at <= %s
           AND a.motivo_perda IS NOT NULL
           {filtro_modelo}
         GROUP BY a.motivo_perda
         ORDER BY contagem DESC, motivo ASC
        """,
        params,
    )
    return [dict(row) for row in await result.fetchall()]


async def _motivos_escalada_top(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: list[UUID] | None,
) -> dict[str, Any]:
    """Agrega escaladas por ``tipo`` (enum) + breakdown por modelo.

    Retorna todos os tipos canônicos (mesmo com contagem zero) ordenados desc.
    Mantém ``top5/outros_total/total`` para retrocompatibilidade enquanto o
    frontend novo não estabiliza — esses derivados usam o rótulo humano.
    """
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT e.tipo::text AS tipo,
               a.modelo_id AS modelo_id,
               m.nome AS modelo_nome,
               COUNT(*)::int AS contagem
          FROM barravips.escaladas e
          JOIN barravips.atendimentos a ON a.id = e.atendimento_id
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE e.aberta_em >= %s AND e.aberta_em <= %s {filtro_modelo}
         GROUP BY e.tipo, a.modelo_id, m.nome
        """,
        params,
    )
    linhas = list(await result.fetchall())

    agrupado: dict[str, dict[str, Any]] = {}
    for row in linhas:
        tipo = str(row["tipo"])
        bucket = agrupado.setdefault(tipo, {"contagem": 0, "por_modelo": []})
        bucket["contagem"] += int(row["contagem"])
        bucket["por_modelo"].append(
            {
                "modelo_id": str(row["modelo_id"]),
                "nome": row["modelo_nome"],
                "contagem": int(row["contagem"]),
            }
        )

    por_tipo: list[dict[str, Any]] = []
    for tipo_enum in TipoEscalada:
        bucket = agrupado.get(tipo_enum.value, {"contagem": 0, "por_modelo": []})
        bucket["por_modelo"].sort(key=lambda r: (-r["contagem"], r["nome"]))
        por_tipo.append(
            {
                "tipo": tipo_enum.value,
                "rotulo": rotulo_tipo_escalada(tipo_enum),
                "contagem": bucket["contagem"],
                "por_modelo": bucket["por_modelo"],
            }
        )
    por_tipo.sort(key=lambda r: (-r["contagem"], r["rotulo"]))

    total = sum(item["contagem"] for item in por_tipo)
    top5 = [
        {"motivo": item["rotulo"], "tipo": item["tipo"], "contagem": item["contagem"]}
        for item in por_tipo
        if item["contagem"] > 0
    ][:5]
    outros_total = max(total - sum(item["contagem"] for item in top5), 0)

    return {
        "por_tipo": por_tipo,
        "top5": top5,
        "outros_total": outros_total,
        "total": total,
    }


async def _profissionais(
    conn: AsyncConnection[Any],
    janela: Janela,
) -> list[dict[str, Any]]:
    # O ranking sempre lista TODAS as modelos; o multi-select do dashboard destaca
    # as selecionadas no frontend, sem filtrar esta seção. Os placeholders de filtro
    # ficam vazios para preservar o formato da query (CTEs por janela).
    filtro_modelo_volume = ""
    filtro_modelo_fech = ""
    filtro_modelo_imp = ""
    filtro_modelo_perd = ""
    filtro_modelo_join = ""
    params: list[Any] = [
        janela.inicio,
        janela.fim,  # volume CTE
        janela.inicio,
        janela.fim,  # fech CTE
        janela.inicio,
        janela.fim,  # perd CTE
    ]

    result = await conn.execute(
        f"""
        WITH volume AS (
          SELECT a.modelo_id, COUNT(*)::int AS volume
            FROM barravips.atendimentos a
           WHERE a.created_at >= %s AND a.created_at <= %s {filtro_modelo_volume}
           GROUP BY a.modelo_id
        ),
        fech AS (
          -- Fórmula espelhada em barra/dominio/painel/routes.py:198-217
          -- (mesma decomposição de bruto/líquido/repasse usada em _fechamentos).
          SELECT a.modelo_id,
                 COUNT(DISTINCT a.id)::int AS contagem,
                 COALESCE(SUM(a.valor_final), 0)::numeric AS valor_bruto,
                 COALESCE(SUM(
                   (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
                 ), 0)::numeric AS valor_liquido,
                 COALESCE(SUM(
                   (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * COALESCE(a.percentual_repasse_snapshot, 0) / 100
                 ), 0)::numeric AS valor_repasse_modelo
            FROM barravips.atendimentos a
            JOIN LATERAL (
              -- Ancora dedupada (ver _fechamentos): 1 fechado_registrado/atendimento p/ nao inflar
              -- os SUM de valor sob correcao Fechado->Perdido->Fechado. COUNT(DISTINCT) ja era imune;
              -- as somas de dinheiro nao. Espelha financeiro/repo.py (ADR 0011, mesmo numero).
              SELECT created_at, tipo
                FROM barravips.eventos
               WHERE atendimento_id = a.id
                 AND tipo = 'fechado_registrado'
               ORDER BY created_at DESC
               LIMIT 1
            ) e ON true
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             AND e.created_at >= %s AND e.created_at <= %s {filtro_modelo_fech}
           GROUP BY a.modelo_id
        ),
        fech_imp AS (
          -- Fechados IMPORTADOS sem evento `fechado_registrado` (histórico do caderno do
          -- vendedor, sem data). O recorte por período acima os ignora (ancora no evento,
          -- regime caixa ADR 0011), então o ranking mostraria fechamentos/valor zerados
          -- mesmo com R$ reais no histórico. Espelha financeiro/repo.importados_sem_data:
          -- mesma definição (Fechado + NOT EXISTS evento), ignorando a janela. Mesma
          -- decomposição bruto/líquido/repasse da CTE `fech`.
          SELECT a.modelo_id,
                 COUNT(*)::int AS contagem,
                 COALESCE(SUM(a.valor_final), 0)::numeric AS valor_bruto,
                 COALESCE(SUM(
                   (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
                 ), 0)::numeric AS valor_liquido,
                 COALESCE(SUM(
                   (a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * COALESCE(a.percentual_repasse_snapshot, 0) / 100
                 ), 0)::numeric AS valor_repasse_modelo
            FROM barravips.atendimentos a
           WHERE a.estado = 'Fechado'
             AND NOT EXISTS (
               SELECT 1 FROM barravips.eventos e
                WHERE e.atendimento_id = a.id
                  AND e.tipo = 'fechado_registrado'
             )
             {filtro_modelo_imp}
           GROUP BY a.modelo_id
        ),
        perd AS (
          SELECT a.modelo_id, COUNT(DISTINCT a.id)::int AS contagem
            FROM barravips.atendimentos a
            JOIN barravips.eventos e ON e.atendimento_id = a.id
           WHERE a.estado = 'Perdido'
             AND e.tipo = 'perdido_registrado'
             AND e.created_at >= %s AND e.created_at <= %s {filtro_modelo_perd}
           GROUP BY a.modelo_id
        )
        -- fechamentos/valor exibidos = com evento na janela + importados (sem data); a TAXA
        -- de conversão (no Python) usa só `fechamentos_periodo`, pois não há perdas importadas
        -- e contar os importados como fechados infla a conversão para ~100% (enganoso).
        SELECT m.id AS modelo_id, m.nome AS modelo_nome,
               COALESCE(v.volume, 0)::int AS volume,
               COALESCE(f.contagem, 0)::int AS fechamentos_periodo,
               (COALESCE(f.contagem, 0) + COALESCE(fi.contagem, 0))::int AS fechamentos,
               (COALESCE(f.valor_bruto, 0) + COALESCE(fi.valor_bruto, 0))::numeric AS valor_bruto,
               (COALESCE(f.valor_liquido, 0) + COALESCE(fi.valor_liquido, 0))::numeric AS valor_liquido,
               (COALESCE(f.valor_repasse_modelo, 0) + COALESCE(fi.valor_repasse_modelo, 0))::numeric AS valor_repasse_modelo,
               COALESCE(p.contagem, 0)::int AS perdas
          FROM barravips.modelos m
          LEFT JOIN volume v ON v.modelo_id = m.id
          LEFT JOIN fech f ON f.modelo_id = m.id
          LEFT JOIN fech_imp fi ON fi.modelo_id = m.id
          LEFT JOIN perd p ON p.modelo_id = m.id
          {filtro_modelo_join}
         ORDER BY volume DESC, valor_bruto DESC, m.nome ASC
        """,
        params,
    )
    rows = list(await result.fetchall())

    profissionais = []
    for row in rows:
        # Conversão sobre o desfecho COM evento na janela (não os importados sem data):
        # importados não têm perda registrada, então contá-los inflaria a taxa para ~100%.
        decididos = int(row["fechamentos_periodo"]) + int(row["perdas"])
        taxa = (int(row["fechamentos_periodo"]) / decididos * 100) if decididos > 0 else None
        profissionais.append(
            {
                "modelo": {"id": str(row["modelo_id"]), "nome": row["modelo_nome"]},
                "volume": int(row["volume"]),
                "fechamentos": int(row["fechamentos"]),
                "perdas": int(row["perdas"]),
                "valor_bruto_brl": round(float(row["valor_bruto"]), 2),
                "valor_liquido_brl": round(float(row["valor_liquido"]), 2),
                "valor_repasse_modelo_brl": round(float(row["valor_repasse_modelo"]), 2),
                "taxa_conversao_pct": round(taxa, 1) if taxa is not None else None,
                "n_referencia": decididos,
            }
        )
    return profissionais


# -----------------------------------------------------------------------------
# Série temporal — sparklines
# -----------------------------------------------------------------------------


async def _serie(
    conn: AsyncConnection[Any],
    metrica: str,
    unidade: str,
    n: int,
    modelo_id: list[UUID] | None,
) -> list[dict[str, Any]]:
    """Roda a query de série apropriada para a métrica solicitada.

    Garante ``n`` pontos no retorno (preenche com zero quando não há dado),
    ordenados do mais antigo para o mais recente.
    """
    if metrica == "conversao":
        return await _serie_conversao(conn, unidade, n, modelo_id)
    if metrica == "fechamentos":
        return await _serie_contagem_evento(conn, unidade, n, modelo_id, "fechado_registrado")
    if metrica == "perdas":
        return await _serie_contagem_evento(conn, unidade, n, modelo_id, "perdido_registrado")
    if metrica == "escaladas":
        return await _serie_escaladas(conn, unidade, n, modelo_id)
    if metrica == "liquido":
        return await _serie_financeiro(conn, unidade, n, modelo_id, "liquido")
    if metrica == "bruto":
        return await _serie_financeiro(conn, unidade, n, modelo_id, "bruto")
    return []


def _trunc(unidade: str) -> str:
    # Mapeado de SERIE_UNIDADES — funcao chamada so apos validacao do enum.
    return {"dia": "day", "semana": "week"}[unidade]


def _intervalo(unidade: str) -> str:
    return {"dia": "1 day", "semana": "1 week"}[unidade]


async def _serie_contagem_evento(
    conn: AsyncConnection[Any],
    unidade: str,
    n: int,
    modelo_id: list[UUID] | None,
    tipo_evento: str,
) -> list[dict[str, Any]]:
    trunc = _trunc(unidade)
    intervalo = _intervalo(unidade)
    filtro_modelo = ""
    params: list[Any] = [trunc, n - 1, intervalo, trunc, intervalo, trunc, tipo_evento]
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        WITH buckets AS (
          SELECT generate_series(
                   date_trunc(%s, now()) - (%s * %s::interval),
                   date_trunc(%s, now()),
                   %s::interval
                 ) AS bucket
        ),
        dados AS (
          SELECT date_trunc(%s, e.created_at) AS bucket,
                 COUNT(DISTINCT a.id)::int AS valor
            FROM barravips.eventos e
            JOIN barravips.atendimentos a ON a.id = e.atendimento_id
           WHERE e.tipo = %s
             {filtro_modelo}
           GROUP BY 1
        )
        SELECT b.bucket::timestamptz AS bucket,
               COALESCE(d.valor, 0)::int AS valor
          FROM buckets b
          LEFT JOIN dados d ON d.bucket = b.bucket
         ORDER BY b.bucket
        """,
        params,
    )
    return [
        {"data": row["bucket"].date().isoformat(), "valor": int(row["valor"])}
        for row in await result.fetchall()
    ]


async def _serie_escaladas(
    conn: AsyncConnection[Any],
    unidade: str,
    n: int,
    modelo_id: list[UUID] | None,
) -> list[dict[str, Any]]:
    trunc = _trunc(unidade)
    intervalo = _intervalo(unidade)
    filtro_modelo = ""
    base_params: list[Any] = [trunc, n - 1, intervalo, trunc, intervalo, trunc]
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        base_params.append(modelo_id)

    result = await conn.execute(
        f"""
        WITH buckets AS (
          SELECT generate_series(
                   date_trunc(%s, now()) - (%s * %s::interval),
                   date_trunc(%s, now()),
                   %s::interval
                 ) AS bucket
        ),
        dados AS (
          SELECT date_trunc(%s, e.aberta_em) AS bucket,
                 COUNT(*)::int AS valor
            FROM barravips.escaladas e
            JOIN barravips.atendimentos a ON a.id = e.atendimento_id
           WHERE TRUE {filtro_modelo}
           GROUP BY 1
        )
        SELECT b.bucket::timestamptz AS bucket,
               COALESCE(d.valor, 0)::int AS valor
          FROM buckets b
          LEFT JOIN dados d ON d.bucket = b.bucket
         ORDER BY b.bucket
        """,
        base_params,
    )
    return [
        {"data": row["bucket"].date().isoformat(), "valor": int(row["valor"])}
        for row in await result.fetchall()
    ]


async def _serie_conversao(
    conn: AsyncConnection[Any],
    unidade: str,
    n: int,
    modelo_id: list[UUID] | None,
) -> list[dict[str, Any]]:
    """Taxa de conversão por bucket = fechados / (fechados + perdidos) * 100."""
    trunc = _trunc(unidade)
    intervalo = _intervalo(unidade)
    filtro_modelo = ""
    params: list[Any] = [trunc, n - 1, intervalo, trunc, intervalo, trunc]
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        WITH buckets AS (
          SELECT generate_series(
                   date_trunc(%s, now()) - (%s * %s::interval),
                   date_trunc(%s, now()),
                   %s::interval
                 ) AS bucket
        ),
        dados AS (
          SELECT date_trunc(%s, e.created_at) AS bucket,
                 COUNT(DISTINCT a.id) FILTER (WHERE e.tipo = 'fechado_registrado') AS fechados,
                 COUNT(DISTINCT a.id) FILTER (WHERE e.tipo = 'perdido_registrado') AS perdidos
            FROM barravips.eventos e
            JOIN barravips.atendimentos a ON a.id = e.atendimento_id
           WHERE e.tipo IN ('fechado_registrado', 'perdido_registrado') {filtro_modelo}
           GROUP BY 1
        )
        SELECT b.bucket::timestamptz AS bucket,
               COALESCE(d.fechados, 0)::int AS fechados,
               COALESCE(d.perdidos, 0)::int AS perdidos
          FROM buckets b
          LEFT JOIN dados d ON d.bucket = b.bucket
         ORDER BY b.bucket
        """,
        params,
    )
    pontos: list[dict[str, Any]] = []
    for row in await result.fetchall():
        fechados = int(row["fechados"])
        perdidos = int(row["perdidos"])
        decididos = fechados + perdidos
        valor = (fechados / decididos * 100) if decididos > 0 else None
        pontos.append(
            {
                "data": row["bucket"].date().isoformat(),
                "valor": round(valor, 1) if valor is not None else None,
                "n_referencia": decididos,
            }
        )
    return pontos


async def _serie_financeiro(
    conn: AsyncConnection[Any],
    unidade: str,
    n: int,
    modelo_id: list[UUID] | None,
    componente: str,
) -> list[dict[str, Any]]:
    trunc = _trunc(unidade)
    intervalo = _intervalo(unidade)
    filtro_modelo = ""
    params: list[Any] = [trunc, n - 1, intervalo, trunc, intervalo, trunc]
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = ANY(%s)"
        params.append(modelo_id)

    if componente == "liquido":
        expressao = "(a.valor_final / (1 + COALESCE(a.taxa_cartao_snapshot, 0) / 100)) * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)"
    elif componente == "bruto":
        expressao = "a.valor_final"
    else:
        return []

    result = await conn.execute(
        f"""
        WITH buckets AS (
          SELECT generate_series(
                   date_trunc(%s, now()) - (%s * %s::interval),
                   date_trunc(%s, now()),
                   %s::interval
                 ) AS bucket
        ),
        dados AS (
          SELECT date_trunc(%s, e.created_at) AS bucket,
                 COALESCE(SUM({expressao}), 0)::numeric AS valor
            FROM barravips.atendimentos a
            JOIN LATERAL (
              -- Ancora dedupada (ver _fechamentos): 1 fechado_registrado/atendimento, senao a
              -- soma da sparkline infla sob correcao Fechado->Perdido->Fechado. Espelha o dedup do
              -- modulo financeiro (financeiro/repo.py) -> sparkline e modulo batem (ADR 0011).
              SELECT created_at, tipo
                FROM barravips.eventos
               WHERE atendimento_id = a.id
                 AND tipo = 'fechado_registrado'
               ORDER BY created_at DESC
               LIMIT 1
            ) e ON true
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             {filtro_modelo}
           GROUP BY 1
        )
        SELECT b.bucket::timestamptz AS bucket,
               COALESCE(d.valor, 0)::numeric AS valor
          FROM buckets b
          LEFT JOIN dados d ON d.bucket = b.bucket
         ORDER BY b.bucket
        """,
        params,
    )
    return [
        {"data": row["bucket"].date().isoformat(), "valor": round(float(row["valor"]), 2)}
        for row in await result.fetchall()
    ]
