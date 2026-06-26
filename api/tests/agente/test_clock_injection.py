"""Clock injection (harness fiel/replay): o relogio do turno e injetavel ponta a ponta.

Prova que `criar_bloqueio_previo` honra o `agora` passado (que o agente propaga de
`ContextAgente.agora_utc` via `registrar_extracao_ia`) em vez de `datetime.now()`. Sem isso o
teste do agente diverge da prod nas bordas de agenda (antecedencia/cross-midnight): a IA oferece
um horario ancorado no relogio injetado mas a reserva validava contra o relogio real.

DB real (TEST_DATABASE_URL), seed na mesma transacao, ROLLBACK no teardown — nada commita.
needs_db, SEM needs_key (nenhuma chamada de LLM; so a mecanica de reserva).
"""

import os
from collections.abc import AsyncIterator
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from evals.harness import _seed_atendimento, _seed_cliente, _seed_conversa, _seed_modelo
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.agenda.service import AntecedenciaInsuficiente, criar_bloqueio_previo

pytestmark = pytest.mark.needs_db

_BRT = ZoneInfo("America/Sao_Paulo")
# Data fixa e distante do "hoje" real: se o relogio NAO fosse injetado (caisse no now() real),
# 14:00 nessa data seria passado -> AntecedenciaInsuficiente. Logo, a reserva OK no caso `cedo`
# so e possivel porque o `agora` injetado foi de fato usado.
_DATA = date(2026, 3, 15)
_HORARIO = time(14, 0)


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


async def _seed_atendimento_reservavel(conn: AsyncConnection[dict[str, Any]]) -> dict[str, Any]:
    """Modelo sem regras de disponibilidade (reservavel sempre) + atendimento interno pronto p/
    reservar. Devolve o dict no formato que `criar_bloqueio_previo` espera."""
    modelo_id = await _seed_modelo(conn, {})
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        recorrente=False,
        observacoes_internas=None,
    )
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        numero_curto=1,
        atendimento={"estado": "Aguardando_confirmacao", "tipo_atendimento": "interno"},
    )
    return {
        "id": atendimento_id,
        "modelo_id": modelo_id,
        "data_desejada": _DATA,
        "horario_desejado": _HORARIO,
        "duracao_horas": 1,
    }


async def test_agora_injetado_cedo_reserva_no_horario(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`agora` 4h antes do horario combinado -> reserva no slot exato. Prova que a reserva usou o
    relogio injetado (com o now() real essa data ja seria passado)."""
    atend = await _seed_atendimento_reservavel(conn)
    agora = datetime(2026, 3, 15, 10, 0, tzinfo=_BRT)

    await criar_bloqueio_previo(conn, atendimento=atend, agora=agora)

    res = await conn.execute(
        "SELECT inicio FROM barravips.bloqueios WHERE atendimento_id = %s",
        (atend["id"],),
    )
    row = await res.fetchone()
    assert row is not None, "bloqueio nao foi criado"
    assert row["inicio"].astimezone(_BRT) == datetime(2026, 3, 15, 14, 0, tzinfo=_BRT)


async def test_agora_injetado_tarde_barra_por_antecedencia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """MESMO atendimento, so o relogio muda: `agora` no proprio horario combinado cai dentro do
    buffer (inicio < agora + buffer) -> AntecedenciaInsuficiente. O contraste com o teste acima
    prova que o `agora` injetado controla o resultado, nao o relogio real."""
    atend = await _seed_atendimento_reservavel(conn)
    agora = datetime(2026, 3, 15, 14, 0, tzinfo=_BRT)

    with pytest.raises(AntecedenciaInsuficiente):
        await criar_bloqueio_previo(conn, atendimento=atend, agora=agora)
