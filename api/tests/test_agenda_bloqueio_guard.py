"""Regressão (achado real do 1º baseline do flywheel): `criar_bloqueio_previo` SEM `horario_desejado`
levanta `HorarioNaoDefinido` (erro recuperável que a tool de Pix converte em instrução p/ a IA),
NUNCA o `TypeError` cru de `datetime.combine(data, None)` que crashava o turno quando o cliente pedia
o Pix de deslocamento antes de cravar a hora. PURO: o guard dispara ANTES de qualquer uso da conexão.
"""

from datetime import date, time
from typing import Any

import pytest

from barra.dominio.agenda.service import (
    ForaDisponibilidade,
    HorarioNaoDefinido,
    criar_bloqueio_previo,
)


def _atendimento(horario, data=None):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "modelo_id": "00000000-0000-0000-0000-000000000002",
        "data_desejada": data,
        "horario_desejado": horario,
        "duracao_horas": 1,
    }


async def test_sem_horario_levanta_recuperavel_nao_typeerror():
    # conn=None de propósito: o guard de horário ausente dispara ANTES de qualquer conn.execute,
    # então não precisa de banco. Antes do fix isto era um TypeError em datetime.combine(data, None).
    with pytest.raises(HorarioNaoDefinido):
        await criar_bloqueio_previo(None, atendimento=_atendimento(None))  # type: ignore[arg-type]


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _Conn:
    """Conn fake: serve as regras de modelo_disponibilidade e registra o que mais rodou."""

    def __init__(self, regras: list[dict[str, Any]]) -> None:
        self.regras = regras
        self.queries: list[str] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "modelo_disponibilidade" in query:
            return _Result(self.regras)
        if "INSERT INTO barravips.bloqueios" in query:
            return _Result([{"id": "00000000-0000-0000-0000-00000000000b"}])
        return _Result([])


# Regra: segundas (DOW Postgres = 1), 14h-18h, período aberto. 2026-06-15 é segunda.
_REGRA_SEGUNDA_TARDE = {
    "data_inicio": date(2026, 6, 1),
    "data_fim": None,
    "dia_semana": 1,
    "hora_inicio": time(14, 0),
    "hora_fim": time(18, 0),
}


async def test_inicio_fora_da_disponibilidade_levanta_trava_dura():
    # ADR 0005: a IA nunca cria bloqueio fora da Disponibilidade ("o sistema impede" — trava de
    # código, não só prompt). Início fora da janela -> ForaDisponibilidade, sem INSERT.
    conn = _Conn([_REGRA_SEGUNDA_TARDE])
    with pytest.raises(ForaDisponibilidade):
        await criar_bloqueio_previo(
            conn,  # type: ignore[arg-type]
            atendimento=_atendimento(time(21, 0), data=date(2026, 6, 15)),
        )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q] == []


async def test_inicio_dentro_da_disponibilidade_reserva_normalmente():
    # Gate valida só o INÍCIO (ADR 0005): 17h cabe na janela 14h-18h mesmo que o fim (18h) a
    # encoste; o INSERT acontece.
    conn = _Conn([_REGRA_SEGUNDA_TARDE])
    await criar_bloqueio_previo(
        conn,  # type: ignore[arg-type]
        atendimento=_atendimento(time(17, 0), data=date(2026, 6, 15)),
    )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q]


async def test_modelo_sem_regra_segue_sempre_reservavel():
    # CONTEXT.md "Disponibilidade": modelo sem nenhuma regra é reservável sempre.
    conn = _Conn([])
    await criar_bloqueio_previo(
        conn,  # type: ignore[arg-type]
        atendimento=_atendimento(time(3, 0), data=date(2026, 6, 15)),
    )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q]
