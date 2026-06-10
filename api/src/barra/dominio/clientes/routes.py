import re
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from barra.api.deps import get_conn, get_user
from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.core.janela import resolver_janela
from barra.dominio.clientes.schemas import ClienteCreate, ClientePatch

router = APIRouter(dependencies=[Depends(get_user)])

_TELEFONE_BR_RE = re.compile(r"^55\d{10,11}$")


def _predicado_periodo(
    periodo: str | None,
    data_inicio: str | None,
    data_fim: str | None,
) -> tuple[str, list[Any]] | None:
    """Predicado EXISTS de "cliente com atendimento na janela", compartilhado pela
    Lista e pelo Mapa. Custom (data_inicio/data_fim) tem precedência; presets
    canônicos (hoje/7d/30d/mes) resolvem via janela BRT; "tudo"/None não filtram."""
    if data_inicio is not None or data_fim is not None:
        ini, fim = _parse_recorte("data", data_inicio, data_fim)
        return (
            "EXISTS (SELECT 1 FROM barravips.atendimentos a "
            "WHERE a.cliente_id = c.id "
            "AND a.created_at >= %s::date "
            "AND a.created_at < (%s::date + INTERVAL '1 day'))",
            [ini, fim],
        )
    if periodo and periodo not in ("tudo", "todos", "custom"):
        try:
            janela = resolver_janela(periodo, None, None)
        except EntradaInvalida:
            return None
        return (
            "EXISTS (SELECT 1 FROM barravips.atendimentos a "
            "WHERE a.cliente_id = c.id "
            "AND (a.created_at AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN %s AND %s)",
            [janela.de, janela.ate],
        )
    return None


@router.get("/clientes")
async def listar_clientes(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: list[UUID] | None = Query(None),
    q: str | None = None,
    periodo: str | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    perfis: list[str] | None = Query(default=None),
    recencia: Literal["ativos", "dormentes"] | None = None,
    valor_min: float | None = None,
    valor_max: float | None = None,
    incluir_arquivados: bool = False,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filtros = ["1=1"]
    if perfis:
        # Preferência DECLARADA, semântica OR: cliente cujo conjunto contém
        # qualquer um dos selecionados (overlap). ADR 0006.
        filtros.append("c.perfis_preferidos && %s::barravips.perfil_fisico_enum[]")
        params.append(perfis)
    if modelo_id:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.conversas cv "
            "WHERE cv.cliente_id = c.id AND cv.modelo_id = ANY(%s))"
        )
        params.append(modelo_id)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    predicado = _predicado_periodo(periodo, data_inicio, data_fim)
    if predicado:
        filtros.append(predicado[0])
        params.extend(predicado[1])
    # Faixa de R$ fechado (ag.valor_total — cross-modelo) e recência sobre a última
    # atividade (ag.ultima_atividade = MAX updated_at). Espelha os filtros do Mapa
    # (MAPA-11); negativos viram NO-OP. ag.* vem do LATERAL agregado abaixo.
    if valor_min is not None and valor_min >= 0:
        filtros.append("ag.valor_total >= %s")
        params.append(valor_min)
    if valor_max is not None and valor_max >= 0:
        filtros.append("ag.valor_total <= %s")
        params.append(valor_max)
    if recencia == "ativos":
        filtros.append("ag.ultima_atividade >= NOW() - INTERVAL '90 days'")
    elif recencia == "dormentes":
        filtros.append("ag.ultima_atividade < NOW() - INTERVAL '90 days'")
    if not incluir_arquivados:
        filtros.append("c.arquivado_em IS NULL")
    if cursor:
        # Cursor composto "timestamp|id": updated_at sozinho não pagina quando há
        # empate (import em lote grava centenas de linhas na mesma transação).
        cursor_ts, _, cursor_id = cursor.partition("|")
        if cursor_id:
            filtros.append("(c.updated_at, c.id) < (%s::timestamptz, %s::uuid)")
            params.extend([cursor_ts, cursor_id])
        else:
            # cursor legado (só timestamp), emitido antes do desempate
            filtros.append("c.updated_at < %s::timestamptz")
            params.append(cursor_ts)
    params.append(limit + 1)
    result = await conn.execute(
        f"""
        SELECT c.id, c.nome, c.telefone, c.primeiro_contato_modelo_id,
               c.arquivado_em, c.created_at, c.updated_at,
               ag.total_atendimentos, ag.total_fechados,
               ag.valor_total, ag.ultima_atividade,
               ag.modelos_distintas, ag.modelo_predominante_nome
          FROM barravips.clientes c
          LEFT JOIN LATERAL (
            SELECT
              COUNT(*) AS total_atendimentos,
              COUNT(*) FILTER (WHERE a.estado = 'Fechado') AS total_fechados,
              COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0) AS valor_total,
              MAX(a.updated_at) AS ultima_atividade,
              COUNT(DISTINCT a.modelo_id) AS modelos_distintas,
              (SELECT m.nome
                 FROM barravips.atendimentos a2
                 JOIN barravips.modelos m ON m.id = a2.modelo_id
                WHERE a2.cliente_id = c.id
                GROUP BY m.id, m.nome
                ORDER BY COUNT(*) DESC, MAX(a2.updated_at) DESC
                LIMIT 1) AS modelo_predominante_nome
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
          ) ag ON TRUE
         WHERE {" AND ".join(filtros)}
         ORDER BY c.updated_at DESC, c.id DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await result.fetchall())
    # next_cursor sai da última linha EXIBIDA (rows[-1] pré-truncate era a linha
    # extra do limit+1 — com "<" estrito ela nunca aparecia: 1 cliente sumia por página)
    tem_mais = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        f"{rows[-1]['updated_at'].isoformat()}|{rows[-1]['id']}" if tem_mais and rows else None
    )
    return {
        "items": [
            {
                "id": row["id"],
                "nome": row["nome"],
                "telefone_mascarado": _mascarar_telefone(row["telefone"]),
                "primeiro_contato_modelo_id": row["primeiro_contato_modelo_id"],
                "arquivado_em": row["arquivado_em"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "total_atendimentos": row["total_atendimentos"] or 0,
                "valor_total": row["valor_total"] or 0,
                "ultima_atividade": row["ultima_atividade"],
                "modelos_distintas": row["modelos_distintas"] or 0,
                "modelo_predominante_nome": row["modelo_predominante_nome"],
                "recorrente": (row["total_fechados"] or 0) >= 2,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/clientes/mapa")
async def mapa_clientes(
    conn: AsyncConnection[Any] = Depends(get_conn),
    modelo_id: list[UUID] | None = Query(None),
    q: str | None = None,
    periodo: str | None = None,
    perfis: list[str] | None = Query(default=None),
    incluir_arquivados: bool = False,
    desfecho: Literal["Fechado", "Perdido", "andamento"] | None = None,
    motivos_perda: list[str] | None = Query(default=None, alias="motivo_perda"),
    valor_min: float | None = None,
    valor_max: float | None = None,
    recencia: Literal["ativos", "dormentes"] | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    comparar: bool = False,
    a_inicio: str | None = None,
    a_fim: str | None = None,
    b_inicio: str | None = None,
    b_fim: str | None = None,
) -> dict[str, Any]:
    """Pontos do **Mapa de clientes** (ADR 0008): 1 ponto por cliente na localização do
    atendimento **externo** mais recente com `lat/lng`. Interno fica de fora (lá o endereço é o
    ponto de encontro na modelo, não onde o cliente mora). Cliente sem externo geocodificado não
    vira ponto e entra em `total_sem_localizacao`. Sem paginação — o mapa é agregado. Filtros
    espelham `listar_clientes` (menos cursor); os totais por ponto agregam todas as modelos.

    MAPA-8: aceita `desfecho` (Fechado/Perdido/andamento) e `motivo_perda` (multi, OR) que
    incidem sobre o **mesmo atendimento** que ancora o ponto (via o LATERAL `geo`). Cliente
    cujo externo mais recente não bate no filtro simplesmente não vira ponto — não entra em
    `total_sem_localizacao` (esse campo é reservado a clientes sem geo).

    MAPA-11: aceita `valor_min`/`valor_max` (R$ fechado do cliente, incide em `ag.valor_total`
    — cross-modelo) e `recencia` ("ativos" = `geo.ultima_data >= NOW() - 90d`; "dormentes" = <).
    Negativos viram NO-OP. Ortogonais aos filtros do MAPA-8 e à lente MAPA-9 (sempre aplicados).

    Task 9: aceita `data_inicio`/`data_fim` (ISO `YYYY-MM-DD`) — o "Período personalizado" do
    filtro simples. Quando ambos vêm, filtra clientes com algum atendimento em
    `[data_inicio, data_fim+1 day)` (mesma forma do preset `periodo`, só que com janela
    explícita) e tem precedência sobre `periodo`. `fim < inicio` → 422 (espelha o modo
    Comparar). Combina com os filtros de modelo/perfil já existentes (mesmo WHERE).

    MAPA-14: aceita `comparar=true` com dois recortes (`a_inicio`/`a_fim`, `b_inicio`/`b_fim`,
    ISO `YYYY-MM-DD`). Quando ativo, ignora `periodo` e `recencia` (não fazem sentido) e
    devolve um ponto por par (cliente, recorte) com `recorte: "A" | "B"` — cliente com externo
    em A e B aparece duas vezes; `valor_total`/`total_atendimentos` são **do recorte**. Ranges
    podem ou não se sobrepor; só bloqueia quando `fim < inicio` (422). `total_sem_localizacao`
    devolve 0 no modo comparar (a noção 'cliente sem geo' fica ambígua entre recortes — o
    contador é específico do modo agregado padrão)."""
    # Declarado ANTES de GET /clientes/{cliente_id} para "mapa" não cair no path param UUID.
    if comparar:
        a_ini, a_fi = _parse_recorte("a", a_inicio, a_fim)
        b_ini, b_fi = _parse_recorte("b", b_inicio, b_fim)
        return await _mapa_clientes_comparar(
            conn,
            modelo_id=modelo_id,
            q=q,
            perfis=perfis,
            incluir_arquivados=incluir_arquivados,
            desfecho=desfecho,
            motivos_perda=motivos_perda,
            valor_min=valor_min,
            valor_max=valor_max,
            a_inicio=a_ini,
            a_fim=a_fi,
            b_inicio=b_ini,
            b_fim=b_fi,
        )
    params: list[Any] = []
    filtros = ["1=1"]
    if perfis:
        filtros.append("c.perfis_preferidos && %s::barravips.perfil_fisico_enum[]")
        params.append(perfis)
    if modelo_id:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.conversas cv "
            "WHERE cv.cliente_id = c.id AND cv.modelo_id = ANY(%s))"
        )
        params.append(modelo_id)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    # "Período personalizado" tem precedência sobre o preset `periodo` (já tratado
    # dentro de `_predicado_periodo`). Mesma janela usada na Lista.
    predicado = _predicado_periodo(periodo, data_inicio, data_fim)
    if predicado:
        filtros.append(predicado[0])
        params.extend(predicado[1])
    if not incluir_arquivados:
        filtros.append("c.arquivado_em IS NULL")
    # MAPA-8: filtros sobre o atendimento que ancora o ponto. Atuam DEPOIS do LATERAL,
    # no mesmo WHERE — cliente cuja `geo.estado/motivo_perda` não bate fica fora dos
    # pontos sem entrar em `total_sem_localizacao` (esse continua sendo "cliente sem
    # externo geocodificado", coerente com o ADR 0008).
    if desfecho == "Fechado":
        filtros.append("geo.estado = 'Fechado'")
    elif desfecho == "Perdido":
        filtros.append("geo.estado = 'Perdido'")
    elif desfecho == "andamento":
        filtros.append("geo.estado NOT IN ('Fechado', 'Perdido')")
    if motivos_perda:
        filtros.append("geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])")
        params.append(motivos_perda)
    # MAPA-11: faixa de R$ fechado do cliente (ag.valor_total — cross-modelo) e recência
    # sobre `geo.ultima_data` (data do externo que ancora o ponto). Ortogonais ao MAPA-8 e
    # à lente MAPA-9: aplicados sempre. Negativos viram NO-OP (defesa contra querystring
    # adulterada; a UI já valida e bloqueia min > max no trigger).
    if valor_min is not None and valor_min >= 0:
        filtros.append("ag.valor_total >= %s")
        params.append(valor_min)
    if valor_max is not None and valor_max >= 0:
        filtros.append("ag.valor_total <= %s")
        params.append(valor_max)
    if recencia == "ativos":
        filtros.append("geo.ultima_data >= NOW() - INTERVAL '90 days'")
    elif recencia == "dormentes":
        filtros.append("geo.ultima_data < NOW() - INTERVAL '90 days'")
    result = await conn.execute(
        f"""
        SELECT c.id, c.nome, c.perfis_preferidos,
               geo.latitude, geo.longitude, geo.bairro, geo.endereco_formatado, geo.estado,
               geo.motivo_perda, geo.ultima_data,
               ag.total_atendimentos, ag.total_fechados, ag.valor_total
          FROM barravips.clientes c
          LEFT JOIN LATERAL (
            SELECT a.latitude, a.longitude, a.bairro, a.endereco_formatado, a.estado,
                   a.motivo_perda,
                   a.created_at AS ultima_data
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
               AND a.tipo_atendimento = 'externo'
               AND a.latitude IS NOT NULL
             ORDER BY a.created_at DESC
             LIMIT 1
          ) geo ON TRUE
          LEFT JOIN LATERAL (
            SELECT COUNT(*) AS total_atendimentos,
                   COUNT(*) FILTER (WHERE a.estado = 'Fechado') AS total_fechados,
                   COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0) AS valor_total
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
          ) ag ON TRUE
         WHERE {" AND ".join(filtros)}
        """,
        params,
    )
    rows = list(await result.fetchall())
    pontos = [
        {
            "cliente_id": row["id"],
            "nome": row["nome"],
            # numeric(10,7) chega como Decimal; converte p/ float (JSON number) ao front.
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "bairro": row["bairro"],
            "endereco_formatado": row["endereco_formatado"],
            # Desfecho do mesmo atendimento que ancora o ponto (MAPA-3, ADR 0008).
            "estado": row["estado"],
            # Motivo de perda do MESMO atendimento (MAPA-8). Só não-nulo quando
            # estado == 'Perdido' (CHECK constraint do schema).
            "motivo_perda": row["motivo_perda"],
            # Perfil físico DECLARADO (ADR 0006). Nunca o breakdown calculado, que
            # é cross-modelo e quebraria o isolamento por par cliente-modelo (MAPA-10).
            "perfis": _array_text(row["perfis_preferidos"]),
            "total_atendimentos": row["total_atendimentos"] or 0,
            "valor_total": row["valor_total"] or 0,
            # Data do atendimento externo que ancora o ponto (MAPA-5, ADR 0008).
            "ultima_data": row["ultima_data"],
            # Recorrente cross-modelo: ≥2 fechados, mesma regra de listar_clientes.
            "recorrente": (row["total_fechados"] or 0) >= 2,
        }
        for row in rows
        if row["latitude"] is not None
    ]
    total_sem_localizacao = sum(1 for row in rows if row["latitude"] is None)
    return {"pontos": pontos, "total_sem_localizacao": total_sem_localizacao}


# MAPA-14: parse + valida um recorte (inicio/fim) recebidos como YYYY-MM-DD.
# Ambos são obrigatórios quando `comparar=true`; `fim < inicio` vira 422.
def _parse_recorte(rotulo: str, inicio: str | None, fim: str | None) -> tuple[date, date]:
    if inicio is None or fim is None:
        raise EntradaInvalida(
            code="COMPARAR_RECORTE_INCOMPLETO",
            message=(f"Comparar exige {rotulo}_inicio e {rotulo}_fim (YYYY-MM-DD)."),
        )
    try:
        ini = date.fromisoformat(inicio)
        fi = date.fromisoformat(fim)
    except ValueError as exc:
        raise EntradaInvalida(
            code="COMPARAR_DATA_INVALIDA",
            message=f"{rotulo}_inicio/{rotulo}_fim devem ser ISO YYYY-MM-DD.",
        ) from exc
    if fi < ini:
        raise EntradaInvalida(
            code="COMPARAR_RECORTE_VAZIO",
            message=f"{rotulo}_fim ({fim}) é anterior a {rotulo}_inicio ({inicio}).",
        )
    return ini, fi


async def _mapa_clientes_comparar(
    conn: AsyncConnection[Any],
    *,
    modelo_id: list[UUID] | None,
    q: str | None,
    perfis: list[str] | None,
    incluir_arquivados: bool,
    desfecho: str | None,
    motivos_perda: list[str] | None,
    valor_min: float | None,
    valor_max: float | None,
    a_inicio: date,
    a_fim: date,
    b_inicio: date,
    b_fim: date,
) -> dict[str, Any]:
    """Modo comparar do MAPA-14: dois recortes temporais (A e B), 1 ponto por par
    (cliente, recorte). Cliente que tem externo geocodificado em A e B vira 2 pontos.
    Agregados (`valor_total`/`total_atendimentos`) são do recorte — clientes que existiam
    antes mas não tiveram atividade no recorte ficam com 0 (ou não geram ponto).

    Implementado como UNION ALL de duas seleções idênticas, cada uma com janelas
    `[inicio, fim+1 day)` em `created_at`. Filtros base (perfis/modelo_id/q/arquivados/
    desfecho/motivo_perda/valor_min/valor_max) replicados nos dois ramos."""
    base_filtros, base_params = _filtros_base_comparar(
        modelo_id=modelo_id,
        q=q,
        perfis=perfis,
        incluir_arquivados=incluir_arquivados,
        desfecho=desfecho,
        motivos_perda=motivos_perda,
        valor_min=valor_min,
        valor_max=valor_max,
    )
    sql_a, params_a = _ramo_recorte("A", a_inicio, a_fim, base_filtros, base_params)
    sql_b, params_b = _ramo_recorte("B", b_inicio, b_fim, base_filtros, base_params)
    sql = f"{sql_a}\nUNION ALL\n{sql_b}"
    result = await conn.execute(sql, params_a + params_b)
    rows = list(await result.fetchall())
    pontos = [
        {
            "cliente_id": row["id"],
            "nome": row["nome"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "bairro": row["bairro"],
            "endereco_formatado": row["endereco_formatado"],
            "estado": row["estado"],
            "motivo_perda": row["motivo_perda"],
            "perfis": _array_text(row["perfis_preferidos"]),
            "total_atendimentos": row["total_atendimentos"] or 0,
            "valor_total": row["valor_total"] or 0,
            "ultima_data": row["ultima_data"],
            "recorrente": (row["total_fechados"] or 0) >= 2,
            # MAPA-14: 'A' = recorte base; 'B' = recorte de comparação.
            "recorte": row["recorte"],
        }
        for row in rows
        if row["latitude"] is not None
    ]
    # `total_sem_localizacao` não tem semântica clara no modo comparar (sem em A?
    # em B? em ambos?). Zerado e documentado — o frontend não usa esse contador
    # quando comparar=on.
    return {"pontos": pontos, "total_sem_localizacao": 0}


def _filtros_base_comparar(
    *,
    modelo_id: list[UUID] | None,
    q: str | None,
    perfis: list[str] | None,
    incluir_arquivados: bool,
    desfecho: str | None,
    motivos_perda: list[str] | None,
    valor_min: float | None,
    valor_max: float | None,
) -> tuple[list[str], list[Any]]:
    """Filtros ortogonais ao recorte (modelo/perfis/q/arquivados/desfecho/motivo/valor).
    Recência e `periodo` ficam de fora — não fazem sentido junto do range explícito."""
    filtros: list[str] = ["1=1"]
    params: list[Any] = []
    if perfis:
        filtros.append("c.perfis_preferidos && %s::barravips.perfil_fisico_enum[]")
        params.append(perfis)
    if modelo_id:
        filtros.append(
            "EXISTS (SELECT 1 FROM barravips.conversas cv "
            "WHERE cv.cliente_id = c.id AND cv.modelo_id = ANY(%s))"
        )
        params.append(modelo_id)
    if q:
        filtros.append("(c.nome ILIKE %s OR c.telefone ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if not incluir_arquivados:
        filtros.append("c.arquivado_em IS NULL")
    if desfecho == "Fechado":
        filtros.append("geo.estado = 'Fechado'")
    elif desfecho == "Perdido":
        filtros.append("geo.estado = 'Perdido'")
    elif desfecho == "andamento":
        filtros.append("geo.estado NOT IN ('Fechado', 'Perdido')")
    if motivos_perda:
        filtros.append("geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])")
        params.append(motivos_perda)
    if valor_min is not None and valor_min >= 0:
        filtros.append("ag.valor_total >= %s")
        params.append(valor_min)
    if valor_max is not None and valor_max >= 0:
        filtros.append("ag.valor_total <= %s")
        params.append(valor_max)
    return filtros, params


def _ramo_recorte(
    rotulo: str,
    inicio: date,
    fim: date,
    base_filtros: list[str],
    base_params: list[Any],
) -> tuple[str, list[Any]]:
    """Constrói o SELECT de um recorte (A ou B). `geo` é o externo mais recente
    DENTRO da janela; `ag` agrega TODOS os atendimentos do cliente DENTRO da janela.
    Limite superior usa `< fim+1 day` para incluir o dia inteiro do `fim`."""
    # Params específicos do recorte: 2 pares (geo + ag), inicio e fim em cada par.
    recorte_params: list[Any] = [inicio, fim, inicio, fim]
    sql = f"""
        SELECT %s::text AS recorte,
               c.id, c.nome, c.perfis_preferidos,
               geo.latitude, geo.longitude, geo.bairro, geo.endereco_formatado, geo.estado,
               geo.motivo_perda, geo.ultima_data,
               ag.total_atendimentos, ag.total_fechados, ag.valor_total
          FROM barravips.clientes c
          LEFT JOIN LATERAL (
            SELECT a.latitude, a.longitude, a.bairro, a.endereco_formatado, a.estado,
                   a.motivo_perda,
                   a.created_at AS ultima_data
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
               AND a.tipo_atendimento = 'externo'
               AND a.latitude IS NOT NULL
               AND a.created_at >= %s::date
               AND a.created_at < (%s::date + INTERVAL '1 day')
             ORDER BY a.created_at DESC
             LIMIT 1
          ) geo ON TRUE
          LEFT JOIN LATERAL (
            SELECT COUNT(*) AS total_atendimentos,
                   COUNT(*) FILTER (WHERE a.estado = 'Fechado') AS total_fechados,
                   COALESCE(SUM(a.valor_final) FILTER (WHERE a.estado = 'Fechado'), 0) AS valor_total
              FROM barravips.atendimentos a
             WHERE a.cliente_id = c.id
               AND a.created_at >= %s::date
               AND a.created_at < (%s::date + INTERVAL '1 day')
          ) ag ON TRUE
         WHERE {" AND ".join(base_filtros)}
    """
    # Ordem: %s do SELECT (rotulo) → 2x %s do geo → 2x %s do ag → ...base_params.
    params = [rotulo, *recorte_params, *base_params]
    return sql, params


@router.post("/clientes", status_code=201)
async def criar_cliente(
    body: ClienteCreate,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    telefone = _normalizar_telefone_br(body.telefone)
    nome = body.nome.strip() if isinstance(body.nome, str) else None
    if nome == "":
        nome = None
    try:
        row = await _one(
            conn,
            """
            INSERT INTO barravips.clientes (nome, telefone, perfis_preferidos)
            VALUES (%s, %s, %s)
            RETURNING id, nome, telefone, perfis_preferidos,
                      primeiro_contato_modelo_id,
                      arquivado_em, created_at, updated_at
            """,
            (nome, telefone, body.perfis_preferidos),
        )
    except UniqueViolation as exc:
        raise ConflitoEstado("telefone_duplicado") from exc
    assert row is not None
    return {
        "id": row["id"],
        "nome": row["nome"],
        "telefone": row["telefone"],
        "telefone_mascarado": _mascarar_telefone(row["telefone"]),
        "perfis_preferidos": _array_text(row["perfis_preferidos"]),
        "primeiro_contato_modelo_id": row["primeiro_contato_modelo_id"],
        "arquivado_em": row["arquivado_em"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/clientes/{cliente_id}")
async def obter_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT * FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    conversas = await _all(
        conn,
        """
        SELECT cv.id, cv.modelo_id, cv.recorrente, cv.ultimo_motivo_perda,
               cv.ultima_mensagem_em, cv.observacoes_internas,
               m.nome AS modelo_nome
          FROM barravips.conversas cv
          JOIN barravips.modelos m ON m.id = cv.modelo_id
         WHERE cv.cliente_id = %s
         ORDER BY cv.ultima_mensagem_em DESC NULLS LAST, cv.updated_at DESC
        """,
        (cliente_id,),
    )
    return {
        "cliente": {
            "id": cliente["id"],
            "nome": cliente["nome"],
            "telefone_mascarado": _mascarar_telefone(cliente["telefone"]),
            "perfis_preferidos": _array_text(cliente["perfis_preferidos"]),
            "primeiro_contato_modelo_id": cliente["primeiro_contato_modelo_id"],
            "arquivado_em": cliente["arquivado_em"],
            "created_at": cliente["created_at"],
            "updated_at": cliente["updated_at"],
        },
        "conversas": conversas,
    }


@router.patch("/clientes/{cliente_id}")
async def editar_cliente(
    cliente_id: UUID,
    body: ClientePatch,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    async with conn.transaction():
        cliente = await _one(
            conn,
            "SELECT id, telefone FROM barravips.clientes WHERE id = %s",
            (cliente_id,),
        )
        if cliente is None:
            raise NaoEncontrado("Cliente")
        sets: list[str] = []
        valores: list[Any] = []
        if body.nome is not None or "nome" in body.model_fields_set:
            nome = body.nome.strip() if isinstance(body.nome, str) else None
            if nome == "":
                nome = None
            sets.append("nome = %s")
            valores.append(nome)
        if body.telefone is not None:
            telefone = _normalizar_telefone_br(body.telefone)
            # Seeds antigos têm '+5521...' e a normalização tira o '+'; comparamos só dígitos
            # para evitar UPDATE no-op que dispara UNIQUE contra outro cliente que já tem o normalizado.
            atual_digitos = re.sub(r"\D+", "", cliente["telefone"] or "")
            if telefone != atual_digitos:
                sets.append("telefone = %s")
                valores.append(telefone)
        if body.perfis_preferidos is not None:
            sets.append("perfis_preferidos = %s")
            valores.append(body.perfis_preferidos)
        if sets:
            valores.append(cliente_id)
            try:
                await conn.execute(
                    f"UPDATE barravips.clientes SET {', '.join(sets)} WHERE id = %s",
                    valores,
                )
            except UniqueViolation as exc:
                raise ConflitoEstado("telefone_duplicado") from exc
        atualizado = await _one(
            conn,
            "SELECT id, nome, telefone, perfis_preferidos, arquivado_em "
            "FROM barravips.clientes WHERE id = %s",
            (cliente_id,),
        )
    assert atualizado is not None
    return {
        "id": atualizado["id"],
        "nome": atualizado["nome"],
        "telefone": atualizado["telefone"],
        "perfis_preferidos": _array_text(atualizado["perfis_preferidos"]),
        "arquivado_em": atualizado["arquivado_em"],
    }


@router.post("/clientes/{cliente_id}/arquivar")
async def arquivar_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT id, arquivado_em FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    if cliente["arquivado_em"] is None:
        atualizado = await _one(
            conn,
            "UPDATE barravips.clientes SET arquivado_em = NOW() WHERE id = %s "
            "RETURNING id, arquivado_em",
            (cliente_id,),
        )
        assert atualizado is not None
        return {"id": atualizado["id"], "arquivado_em": atualizado["arquivado_em"]}
    return {"id": cliente["id"], "arquivado_em": cliente["arquivado_em"]}


@router.post("/clientes/{cliente_id}/desarquivar")
async def desarquivar_cliente(
    cliente_id: UUID,
    conn: AsyncConnection[Any] = Depends(get_conn),
) -> dict[str, Any]:
    cliente = await _one(
        conn,
        "SELECT id, arquivado_em FROM barravips.clientes WHERE id = %s",
        (cliente_id,),
    )
    if cliente is None:
        raise NaoEncontrado("Cliente")
    if cliente["arquivado_em"] is not None:
        await conn.execute(
            "UPDATE barravips.clientes SET arquivado_em = NULL WHERE id = %s",
            (cliente_id,),
        )
    return {"id": cliente["id"], "arquivado_em": None}


async def _one(
    conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]
) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


async def _all(
    conn: AsyncConnection[Any], query: str, params: tuple[Any, ...]
) -> list[dict[str, Any]]:
    result = await conn.execute(query, params)
    return list(await result.fetchall())


def _mascarar_telefone(telefone: str | None) -> str | None:
    if not telefone:
        return None
    return telefone[:3] + "*****" + telefone[-4:]


def _array_text(value: Any) -> list[str]:
    # psycopg pode devolver enum[] como lista ou como literal '{a,b}'; cobrimos os dois.
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    cleaned = value.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        cleaned = cleaned[1:-1]
    return [item.strip().strip('"') for item in cleaned.split(",") if item.strip()]


def _normalizar_telefone_br(telefone: str) -> str:
    digitos = re.sub(r"\D+", "", telefone or "")
    if not _TELEFONE_BR_RE.match(digitos):
        raise EntradaInvalida(
            code="TELEFONE_INVALIDO",
            message="Telefone invalido. Use formato E.164 BR (55 + DDD + numero).",
        )
    return digitos
