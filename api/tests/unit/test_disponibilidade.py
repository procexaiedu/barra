"""Disponibilidade da modelo (ADR 0005).

`_regra_cobre` é pura (sem banco) — cobre as bordas: janela normal, half-open no fim,
fronteiras de período, data_fim aberta, dia errado, e janela que cruza a meia-noite
(parte do mesmo dia + transbordo do dia anterior). `modelo_disponivel_em` é exercitada
com FakeConn (sem regra => sempre disponível) e, no bloco needs_db, contra o Postgres real.
"""

import os
from collections.abc import AsyncIterator
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.modelos.disponibilidade import (
    BRT,
    _dow_postgres,
    _regra_cobre,
    bloqueios_futuros_fora,
    modelo_disponivel_em,
)


def _regra(
    data_inicio: date,
    data_fim: date | None,
    dia_semana: int,
    hora_inicio: time,
    hora_fim: time,
) -> dict[str, Any]:
    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "dia_semana": dia_semana,
        "hora_inicio": hora_inicio,
        "hora_fim": hora_fim,
    }


# 2026-05-15 é sexta-feira; deriva o dia da semana pelo helper p/ não hardcodar DOW.
_SEX = datetime(2026, 5, 15, 18, 0)
_DOW_SEX = _dow_postgres(_SEX)


def test_janela_normal_dentro() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=18)) is True


def test_janela_normal_antes_do_inicio_da_hora() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=13)) is False


def test_janela_normal_half_open_no_fim() -> None:
    """22:00 está FORA de [14:00, 22:00) — um bloqueio começando às 22:00 não cabe."""
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=22)) is False


def test_janela_normal_inclusiva_no_inicio() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=14, minute=0)) is True


def test_fora_do_periodo_de_datas() -> None:
    regra = _regra(date(2026, 5, 20), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=18)) is False  # 15/05 < 20/05


def test_data_fim_aberta_vale_indefinidamente() -> None:
    regra = _regra(date(2026, 1, 1), None, _DOW_SEX, time(14, 0), time(22, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=18)) is True


def test_dia_da_semana_errado() -> None:
    regra = _regra(
        date(2026, 5, 10), date(2026, 5, 30), (_DOW_SEX + 1) % 7, time(14, 0), time(22, 0)
    )
    assert _regra_cobre(regra, _SEX.replace(hour=18)) is False


def test_cruza_meia_noite_mesmo_dia() -> None:
    """sex 18:00-04:00: 23:00 de sexta está coberto (parte antes da meia-noite)."""
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(18, 0), time(4, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=23)) is True


def test_cruza_meia_noite_antes_da_abertura() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(18, 0), time(4, 0))
    assert _regra_cobre(regra, _SEX.replace(hour=17)) is False


def test_cruza_meia_noite_transbordo_dia_seguinte() -> None:
    """Regra de sexta 18:00-04:00 cobre sábado 02:00 (transbordo)."""
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(18, 0), time(4, 0))
    sabado_02h = datetime(2026, 5, 16, 2, 0)
    assert _regra_cobre(regra, sabado_02h) is True


def test_cruza_meia_noite_transbordo_half_open() -> None:
    """04:00 de sábado está FORA de [.., 04:00)."""
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(18, 0), time(4, 0))
    sabado_04h = datetime(2026, 5, 16, 4, 0)
    assert _regra_cobre(regra, sabado_04h) is False


def test_cruza_meia_noite_transbordo_fora_do_periodo() -> None:
    """Se o período começa só no sábado, o transbordo da sexta anterior não conta."""
    regra = _regra(date(2026, 5, 16), date(2026, 5, 30), _DOW_SEX, time(18, 0), time(4, 0))
    sabado_02h = datetime(2026, 5, 16, 2, 0)
    assert _regra_cobre(regra, sabado_02h) is False


# --- modelo_disponivel_em com FakeConn (sem tocar banco) ---


class _Res:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Conn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Res:
        return _Res(self._rows)


async def test_sem_regra_disponivel_sempre() -> None:
    conn = _Conn([])
    assert await modelo_disponivel_em(conn, uuid4(), _SEX.replace(tzinfo=BRT)) is True


async def test_com_regra_cobrindo() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    conn = _Conn([regra])
    assert await modelo_disponivel_em(conn, uuid4(), _SEX.replace(hour=18, tzinfo=BRT)) is True


async def test_com_regra_nao_cobrindo() -> None:
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    conn = _Conn([regra])
    assert await modelo_disponivel_em(conn, uuid4(), _SEX.replace(hour=8, tzinfo=BRT)) is False


async def test_instante_naive_tratado_como_brt() -> None:
    """Instante sem tzinfo é interpretado como horário local BRT (intenção do operador)."""
    regra = _regra(date(2026, 5, 10), date(2026, 5, 30), _DOW_SEX, time(14, 0), time(22, 0))
    conn = _Conn([regra])
    assert await modelo_disponivel_em(conn, uuid4(), datetime(2026, 5, 15, 18, 0)) is True


# --- needs_db: round-trip real contra o Postgres self-hosted, ROLLBACK sempre ---


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


async def _seed_modelo(connection: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await connection.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno"]),
    )
    return modelo_id


@pytest.mark.needs_db
async def test_round_trip_disponivel_em(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Regra real no banco: instante dentro da janela = True; fora = False (tipos date/time)."""
    modelo_id = await _seed_modelo(conn)
    ter_local = datetime(2026, 6, 2, 18, 0, tzinfo=BRT)  # terça 18:00 BRT
    await conn.execute(
        """
        INSERT INTO barravips.modelo_disponibilidade
          (modelo_id, data_inicio, data_fim, dia_semana, hora_inicio, hora_fim)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            modelo_id,
            date(2026, 6, 1),
            date(2026, 6, 30),
            _dow_postgres(ter_local),
            time(14, 0),
            time(22, 0),
        ),
    )
    assert await modelo_disponivel_em(conn, modelo_id, ter_local) is True
    assert await modelo_disponivel_em(conn, modelo_id, ter_local.replace(hour=8)) is False


@pytest.mark.needs_db
async def test_bloqueios_futuros_fora(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Um bloqueio futuro dentro da janela não aparece; um fora aparece no alerta."""
    modelo_id = await _seed_modelo(conn)
    # A query filtra `b.inicio > now()`; data fixa apodrece quando vira passado. Usa a próxima
    # terça pelo menos uma semana à frente, 18:00 BRT.
    agora = datetime.now(BRT)
    dias_ate_terca = (1 - agora.weekday()) % 7
    ter_local = (agora + timedelta(days=dias_ate_terca + 7)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    await conn.execute(
        """
        INSERT INTO barravips.modelo_disponibilidade
          (modelo_id, data_inicio, data_fim, dia_semana, hora_inicio, hora_fim)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            modelo_id,
            ter_local.date() - timedelta(days=1),
            ter_local.date() + timedelta(days=1),
            _dow_postgres(ter_local),
            time(14, 0),
            time(22, 0),
        ),
    )
    # dentro da janela (terça 18:00) -> não entra no alerta
    await conn.execute(
        "INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (uuid4(), modelo_id, ter_local, ter_local.replace(hour=20), "bloqueado", "manual"),
    )
    # fora da janela (terça 08:00) -> entra no alerta
    await conn.execute(
        "INSERT INTO barravips.bloqueios (id, modelo_id, inicio, fim, estado, origem) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            uuid4(),
            modelo_id,
            ter_local.replace(hour=8),
            ter_local.replace(hour=9),
            "bloqueado",
            "manual",
        ),
    )
    fora = await bloqueios_futuros_fora(conn, modelo_id)
    assert len(fora) == 1
    assert fora[0]["inicio"].startswith(ter_local.strftime("%Y-%m-%d"))


@pytest.mark.needs_db
async def test_rota_put_get_disponibilidade(conn: AsyncConnection[dict[str, Any]]) -> None:
    """PUT substitui as regras e GET as devolve serializadas (exercita o SQL real da rota)."""
    from barra.dominio.modelos.routes import listar_disponibilidade, substituir_disponibilidade
    from barra.dominio.modelos.schemas import DisponibilidadeRegra, DisponibilidadeReplace

    modelo_id = await _seed_modelo(conn)
    body = DisponibilidadeReplace(
        regras=[
            DisponibilidadeRegra(
                data_inicio=date(2026, 6, 1),
                data_fim=date(2026, 6, 30),
                dia_semana=2,
                hora_inicio=time(14, 0),
                hora_fim=time(22, 0),
            ),
            DisponibilidadeRegra(
                data_inicio=date(2026, 6, 1),
                data_fim=None,
                dia_semana=5,
                hora_inicio=time(18, 0),
                hora_fim=time(4, 0),
            ),
        ]
    )
    res = await substituir_disponibilidade(modelo_id, body, conn)
    assert len(res["regras"]) == 2
    assert res["bloqueios_fora"] == []

    got = await listar_disponibilidade(modelo_id, conn)
    assert len(got["regras"]) == 2
    primeira = got["regras"][0]
    assert primeira["hora_inicio"] == "14:00"
    assert primeira["data_fim"] == "2026-06-30"
    assert got["regras"][1]["data_fim"] is None  # período aberto

    # PUT idempotente / replace-all: salvar lista vazia limpa tudo.
    vazio = await substituir_disponibilidade(modelo_id, DisponibilidadeReplace(regras=[]), conn)
    assert vazio["regras"] == []
