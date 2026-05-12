"""Endpoints agregados para a Tela 07 (Dashboard)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from barra.api.deps import get_conn, get_user
from barra.core.errors import EntradaInvalida

router = APIRouter(dependencies=[Depends(get_user)])

BRT = timezone(timedelta(hours=-3))
JANELA_CUSTOM_MAXIMA_DIAS = 90

ESTADOS_CANONICOS: tuple[str, ...] = (
    "Novo",
    "Triagem",
    "Qualificado",
    "Aguardando_confirmacao",
    "Confirmado",
    "Em_execucao",
    "Fechado",
    "Perdido",
)


@dataclass(frozen=True)
class Janela:
    de: date
    ate: date
    inicio: datetime
    fim: datetime

    def dias(self) -> int:
        return (self.ate - self.de).days + 1


@router.get("")
async def dashboard(
    periodo: Literal["hoje", "7d", "30d", "tudo", "custom"] = "7d",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: UUID | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    janela = _resolver_janela(periodo, de, ate)
    # "tudo" abrange toda a operação — comparação com período anterior não faz sentido.
    janela_anterior = _janela_anterior(janela) if periodo != "tudo" else None

    pix_pendentes = await _pix_pendentes_total(conn, modelo_id)
    kpis_periodo = await _kpis(conn, janela, modelo_id)
    kpis_anterior = await _kpis(conn, janela_anterior, modelo_id) if janela_anterior else None
    funil = await _funil_estados(conn, janela, modelo_id)
    perdas = await _perdas_por_motivo(conn, janela, modelo_id)
    escalada_top = await _motivos_escalada_top(conn, janela, modelo_id)
    profissionais = await _profissionais(conn, janela, modelo_id)

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
        "funil_estados": funil,
        "perdas_por_motivo": perdas,
        "motivos_escalada": escalada_top,
        "profissionais": profissionais,
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


@router.get("/escaladas")
async def dashboard_escaladas(
    periodo: Literal["hoje", "7d", "30d", "tudo", "custom"] = "7d",
    de: date | None = None,
    ate: date | None = None,
    modelo_id: UUID | None = None,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    janela = _resolver_janela(periodo, de, ate)

    params: list[Any] = [janela.inicio, janela.fim]
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = e.atendimento_id"
        filtro_modelo = "AND a.modelo_id = %s"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT e.motivo AS motivo, COUNT(*)::int AS contagem
          FROM barravips.escaladas e
          {join}
         WHERE e.aberta_em >= %s AND e.aberta_em <= %s {filtro_modelo}
         GROUP BY e.motivo
         ORDER BY contagem DESC, motivo ASC
        """,
        params,
    )
    motivos = [dict(row) for row in await result.fetchall()]

    return {
        "filtro_aplicado": _filtro_aplicado_dict(periodo, janela, modelo_id),
        "motivos": motivos,
    }


# -----------------------------------------------------------------------------
# Resolução de janela
# -----------------------------------------------------------------------------


def _resolver_janela(periodo: str, de: date | None, ate: date | None) -> Janela:
    hoje = datetime.now(BRT).date()

    if periodo == "custom":
        if de is None or ate is None:
            raise EntradaInvalida(
                "PERIODO_CUSTOM_INVALIDO",
                "Período custom exige 'de' e 'ate'.",
            )
        if de > ate:
            raise EntradaInvalida("PERIODO_CUSTOM_INVALIDO", "'de' deve ser <= 'ate'.")
        if ate > hoje:
            raise EntradaInvalida("PERIODO_CUSTOM_INVALIDO", "'ate' não pode estar no futuro.")
        if (ate - de).days + 1 > JANELA_CUSTOM_MAXIMA_DIAS:
            raise EntradaInvalida(
                "PERIODO_CUSTOM_INVALIDO",
                f"Janela custom limitada a {JANELA_CUSTOM_MAXIMA_DIAS} dias.",
            )
        return _janela_de_datas(de, ate)

    if periodo == "hoje":
        return _janela_de_datas(hoje, hoje)
    if periodo == "7d":
        return _janela_de_datas(hoje - timedelta(days=6), hoje)
    if periodo == "30d":
        return _janela_de_datas(hoje - timedelta(days=29), hoje)
    if periodo == "tudo":
        return _janela_de_datas(date(2020, 1, 1), hoje)

    raise EntradaInvalida("PERIODO_INVALIDO", f"periodo desconhecido: {periodo}")


def _janela_de_datas(de: date, ate: date) -> Janela:
    inicio = datetime.combine(de, time.min, tzinfo=BRT)
    fim = datetime.combine(ate, time.max, tzinfo=BRT)
    return Janela(de=de, ate=ate, inicio=inicio, fim=fim)


def _janela_anterior(janela: Janela) -> Janela | None:
    duracao_dias = janela.dias()
    ate_anterior = janela.de - timedelta(days=1)
    de_anterior = ate_anterior - timedelta(days=duracao_dias - 1)
    return _janela_de_datas(de_anterior, ate_anterior)


def _filtro_aplicado_dict(periodo: str, janela: Janela, modelo_id: UUID | None) -> dict[str, Any]:
    return {
        "periodo": periodo,
        "de": janela.de.isoformat(),
        "ate": janela.ate.isoformat(),
        "modelo_id": str(modelo_id) if modelo_id else None,
    }


# -----------------------------------------------------------------------------
# Consultas
# -----------------------------------------------------------------------------


async def _pix_pendentes_total(conn: AsyncConnection[Any], modelo_id: UUID | None) -> int:
    params: list[Any] = []
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = p.atendimento_id"
        filtro_modelo = "AND a.modelo_id = %s"
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
    modelo_id: UUID | None,
) -> dict[str, Any]:
    fechamentos = await _fechamentos(conn, janela, modelo_id)
    perdas = await _perdas(conn, janela, modelo_id)
    escaladas = await _escaladas_contagem(conn, janela, modelo_id)

    decididos = fechamentos["contagem"] + perdas["contagem"]
    taxa = (fechamentos["contagem"] / decididos * 100) if decididos > 0 else None

    return {
        "taxa_conversao_pct": round(taxa, 1) if taxa is not None else None,
        "fechamentos": fechamentos,
        "perdas": {"contagem": perdas["contagem"]},
        "escaladas": {"contagem": escaladas},
    }


async def _fechamentos(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: UUID | None,
) -> dict[str, Any]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = %s"
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
            a.valor_final * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
          ), 0)::numeric AS valor_liquido,
          COALESCE(SUM(
            a.valor_final * COALESCE(a.percentual_repasse_snapshot, 0) / 100
          ), 0)::numeric AS valor_repasse_modelo,
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
    modelo_id: UUID | None,
) -> dict[str, Any]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = %s"
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
    modelo_id: UUID | None,
) -> int:
    params: list[Any] = [janela.inicio, janela.fim]
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = e.atendimento_id"
        filtro_modelo = "AND a.modelo_id = %s"
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


async def _funil_estados(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: UUID | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND modelo_id = %s"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT estado::text AS estado, COUNT(*)::int AS contagem
          FROM barravips.atendimentos
         WHERE created_at >= %s AND created_at <= %s {filtro_modelo}
         GROUP BY estado
        """,
        params,
    )
    contagens = {row["estado"]: int(row["contagem"]) for row in await result.fetchall()}
    return [{"estado": e, "contagem": contagens.get(e, 0)} for e in ESTADOS_CANONICOS]


async def _perdas_por_motivo(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: UUID | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [janela.inicio, janela.fim]
    filtro_modelo = ""
    if modelo_id:
        filtro_modelo = "AND a.modelo_id = %s"
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
    modelo_id: UUID | None,
) -> dict[str, Any]:
    params: list[Any] = [janela.inicio, janela.fim]
    join = ""
    filtro_modelo = ""
    if modelo_id:
        join = "JOIN barravips.atendimentos a ON a.id = e.atendimento_id"
        filtro_modelo = "AND a.modelo_id = %s"
        params.append(modelo_id)

    result = await conn.execute(
        f"""
        SELECT e.motivo AS motivo, COUNT(*)::int AS contagem
          FROM barravips.escaladas e
          {join}
         WHERE e.aberta_em >= %s AND e.aberta_em <= %s {filtro_modelo}
         GROUP BY e.motivo
         ORDER BY contagem DESC, motivo ASC
        """,
        params,
    )
    todos = [dict(row) for row in await result.fetchall()]
    top5 = todos[:5]
    outros_total = sum(item["contagem"] for item in todos[5:])
    total = sum(item["contagem"] for item in todos)
    return {"top5": top5, "outros_total": outros_total, "total": total}


async def _profissionais(
    conn: AsyncConnection[Any],
    janela: Janela,
    modelo_id: UUID | None,
) -> list[dict[str, Any]]:
    filtro_modelo_volume = ""
    filtro_modelo_fech = ""
    filtro_modelo_perd = ""
    filtro_modelo_join = ""
    params: list[Any] = []
    # volume CTE
    params.extend([janela.inicio, janela.fim])
    if modelo_id:
        filtro_modelo_volume = "AND a.modelo_id = %s"
        params.append(modelo_id)
    # fech CTE
    params.extend([janela.inicio, janela.fim])
    if modelo_id:
        filtro_modelo_fech = "AND a.modelo_id = %s"
        params.append(modelo_id)
    # perd CTE
    params.extend([janela.inicio, janela.fim])
    if modelo_id:
        filtro_modelo_perd = "AND a.modelo_id = %s"
        params.append(modelo_id)
    # SELECT final
    if modelo_id:
        filtro_modelo_join = "WHERE m.id = %s"
        params.append(modelo_id)

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
                   a.valor_final * (1 - COALESCE(a.percentual_repasse_snapshot, 0) / 100)
                 ), 0)::numeric AS valor_liquido,
                 COALESCE(SUM(
                   a.valor_final * COALESCE(a.percentual_repasse_snapshot, 0) / 100
                 ), 0)::numeric AS valor_repasse_modelo
            FROM barravips.atendimentos a
            JOIN barravips.eventos e ON e.atendimento_id = a.id
           WHERE a.estado = 'Fechado'
             AND e.tipo = 'fechado_registrado'
             AND e.created_at >= %s AND e.created_at <= %s {filtro_modelo_fech}
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
        SELECT m.id AS modelo_id, m.nome AS modelo_nome,
               COALESCE(v.volume, 0)::int AS volume,
               COALESCE(f.contagem, 0)::int AS fechamentos,
               COALESCE(f.valor_bruto, 0)::numeric AS valor_bruto,
               COALESCE(f.valor_liquido, 0)::numeric AS valor_liquido,
               COALESCE(f.valor_repasse_modelo, 0)::numeric AS valor_repasse_modelo,
               COALESCE(p.contagem, 0)::int AS perdas
          FROM barravips.modelos m
          LEFT JOIN volume v ON v.modelo_id = m.id
          LEFT JOIN fech f ON f.modelo_id = m.id
          LEFT JOIN perd p ON p.modelo_id = m.id
          {filtro_modelo_join}
         ORDER BY volume DESC, valor_bruto DESC, m.nome ASC
        """,
        params,
    )
    rows = list(await result.fetchall())

    profissionais = []
    for row in rows:
        decididos = int(row["fechamentos"]) + int(row["perdas"])
        taxa = (int(row["fechamentos"]) / decididos * 100) if decididos > 0 else None
        profissionais.append(
            {
                "modelo": {"id": str(row["modelo_id"]), "nome": row["modelo_nome"]},
                "volume": int(row["volume"]),
                "fechamentos": int(row["fechamentos"]),
                "valor_bruto_brl": round(float(row["valor_bruto"]), 2),
                "valor_liquido_brl": round(float(row["valor_liquido"]), 2),
                "valor_repasse_modelo_brl": round(float(row["valor_repasse_modelo"]), 2),
                "taxa_conversao_pct": round(taxa, 1) if taxa is not None else None,
            }
        )
    return profissionais
