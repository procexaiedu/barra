"""Disponibilidade da modelo (ADR 0005; CONTEXT.md "Disponibilidade").

Helpers reutilizáveis: a validação `modelo_disponivel_em` é chamada hoje por
`dominio/agenda/routes.py` (POST/PATCH bloqueios) e, no M3f, pela tool de escrita do
agente. Mora aqui porque o dado (`modelo_disponibilidade`) é do contexto `modelos`.

Convenção de dia da semana: EXTRACT(DOW) do Postgres — 0=domingo .. 6=sábado.
As regras são poucas por modelo; buscamos todas e decidimos a cobertura em Python puro
(`_regra_cobre`), o que mantém a lógica de borda — janela cruzando a meia-noite — testável
sem banco.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection

BRT = ZoneInfo("America/Sao_Paulo")


def _dow_postgres(d: datetime) -> int:
    """Python weekday() (seg=0..dom=6) -> Postgres DOW (dom=0..sáb=6)."""
    return (d.weekday() + 1) % 7


def _no_periodo(d: date, data_inicio: date, data_fim: date | None) -> bool:
    return data_inicio <= d and (data_fim is None or d <= data_fim)


def _regra_cobre(regra: dict[str, Any], loc: datetime) -> bool:
    """True se o instante local `loc` cai na janela da `regra`.

    A janela pertence ao dia da semana do seu início e vai de [hora_inicio, hora_fim).
    Quando `hora_fim <= hora_inicio` ela cruza a meia-noite: a parte antes da meia-noite
    fica no dia civil da regra; a parte depois transborda para o dia civil seguinte (e por
    isso precisamos checar também a regra do dia anterior). hora_fim == hora_inicio = 24h.
    """
    data_inicio: date = regra["data_inicio"]
    data_fim: date | None = regra["data_fim"]
    dia_semana: int = regra["dia_semana"]
    hora_inicio: time = regra["hora_inicio"]
    hora_fim: time = regra["hora_fim"]
    t = loc.time()
    cruza_meia_noite = hora_fim <= hora_inicio

    # Mesmo dia civil da regra.
    if _dow_postgres(loc) == dia_semana and _no_periodo(loc.date(), data_inicio, data_fim):
        if not cruza_meia_noite:
            if hora_inicio <= t < hora_fim:
                return True
        elif t >= hora_inicio:
            return True

    # Transbordo da regra do dia anterior (só janela que cruza a meia-noite).
    if cruza_meia_noite:
        anterior = loc - timedelta(days=1)
        if (
            _dow_postgres(anterior) == dia_semana
            and _no_periodo(anterior.date(), data_inicio, data_fim)
            and t < hora_fim
        ):
            return True

    return False


def regras_cobrem(regras: list[dict[str, Any]], instante: datetime) -> bool:
    """True se `instante` cai em alguma `regra` (lista vazia = disponível sempre).

    Parte pura de `modelo_disponivel_em`, reusável sem banco (ex.: o pré-cálculo do slot
    adjacente em `agente/nos/_proximo_livre.py`). Valida só o instante — o fim pode estender além.
    """
    if not regras:
        return True
    loc = (instante if instante.tzinfo else instante.replace(tzinfo=BRT)).astimezone(BRT)
    return any(_regra_cobre(regra, loc) for regra in regras)


def fim_sessao(regras: list[dict[str, Any]], agora: datetime) -> datetime | None:
    """Fim (datetime BRT) da janela de Disponibilidade que cobre `agora`; None se `agora` não cai
    em nenhuma janela ou a lista é vazia (disponível sempre — sem fronteira; o chamador trata).

    Usado pelo roll cross-midnight de `criar_bloqueio_previo`: um horário combinado anterior a
    `agora` no mesmo dia civil mas dentro da MESMA sessão de trabalho ainda aberta (janela que
    atravessa a meia-noite, ex.: 10:00-04:00) pertence ao dia seguinte — a extração ancora "hoje"
    na data enquanto o `horario_minimo` já é do dia seguinte (00:30 às 23:55). `fim_sessao` dá a
    fronteira que distingue esse caso (encerra Sex 04:00 → 00:30 ainda cabe) de um horário
    genuinamente passado (22:00 às 23:55 → fora da sessão). Várias regras cobrindo `agora` → o fim
    mais tarde (união)."""
    if not regras:
        return None
    loc = (agora if agora.tzinfo else agora.replace(tzinfo=BRT)).astimezone(BRT)
    fins: list[datetime] = []
    for regra in regras:
        if not _regra_cobre(regra, loc):
            continue
        hora_inicio: time = regra["hora_inicio"]
        hora_fim: time = regra["hora_fim"]
        cruza_meia_noite = hora_fim <= hora_inicio
        if cruza_meia_noite and loc.time() >= hora_inicio:
            # `agora` está na parte ANTES da meia-noite: a janela só encerra no dia civil seguinte.
            fim = datetime.combine(loc.date() + timedelta(days=1), hora_fim, tzinfo=BRT)
        else:
            # janela do mesmo dia OU transbordo pós-meia-noite: encerra no próprio dia de `loc`.
            fim = datetime.combine(loc.date(), hora_fim, tzinfo=BRT)
        fins.append(fim)
    return max(fins) if fins else None


async def carregar_regras_disponibilidade(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[dict[str, Any]]:
    """Regras cruas de Disponibilidade da modelo (parte de I/O de `modelo_disponivel_em`).

    Extraída para que o chamador que precisa das regras para MAIS de uma checagem no mesmo turno
    (cobertura + `fim_sessao` do roll cross-midnight em `criar_bloqueio_previo`) não bata o banco
    duas vezes."""
    res = await conn.execute(
        """
        SELECT data_inicio, data_fim, dia_semana, hora_inicio, hora_fim
          FROM barravips.modelo_disponibilidade
         WHERE modelo_id = %s
        """,
        (modelo_id,),
    )
    return await res.fetchall()


async def modelo_disponivel_em(
    conn: AsyncConnection[Any], modelo_id: UUID, instante: datetime
) -> bool:
    """True se o INÍCIO de um bloqueio em `instante` cai numa janela de disponibilidade.

    Modelo sem nenhuma regra cadastrada está disponível sempre (preserva o fluxo atual).
    Valida apenas o instante de início — o fim pode estender além (Pernoite dura 12h e
    estoura janelas menores).
    """
    return regras_cobrem(await carregar_regras_disponibilidade(conn, modelo_id), instante)


async def bloqueios_futuros_fora(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[dict[str, Any]]:
    """Bloqueios ativos futuros cujo início caiu FORA da disponibilidade atual.

    Alerta não-bloqueante exibido ao salvar a disponibilidade — nunca deleta/cancela.
    """
    res = await conn.execute(
        """
        SELECT b.id, b.inicio, b.fim, b.estado::text AS estado,
               a.numero_curto, c.nome AS cliente_nome
          FROM barravips.bloqueios b
          LEFT JOIN barravips.atendimentos a ON a.id = b.atendimento_id
          LEFT JOIN barravips.clientes c ON c.id = a.cliente_id
         WHERE b.modelo_id = %s
           AND b.estado IN ('bloqueado', 'em_atendimento')
           AND b.inicio > now()
         ORDER BY b.inicio
        """,
        (modelo_id,),
    )
    fora: list[dict[str, Any]] = []
    for row in await res.fetchall():
        if not await modelo_disponivel_em(conn, modelo_id, row["inicio"]):
            fora.append(
                {
                    "id": str(row["id"]),
                    "inicio": row["inicio"].isoformat(),
                    "fim": row["fim"].isoformat(),
                    "estado": row["estado"],
                    "numero_curto": row["numero_curto"],
                    "cliente_nome": row["cliente_nome"],
                }
            )
    return fora
