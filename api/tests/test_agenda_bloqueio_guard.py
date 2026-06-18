"""Regressão (achado real do 1º baseline do flywheel): `criar_bloqueio_previo` SEM `horario_desejado`
levanta `HorarioNaoDefinido` (erro recuperável que a tool de Pix converte em instrução p/ a IA),
NUNCA o `TypeError` cru de `datetime.combine(data, None)` que crashava o turno quando o cliente pedia
o Pix de deslocamento antes de cravar a hora. PURO: o guard dispara ANTES de qualquer uso da conexão.
"""

from datetime import date, time, timedelta
from typing import Any

import pytest

from barra.dominio.agenda.service import (
    AntecedenciaInsuficiente,
    ConflitoAgenda,
    ForaDisponibilidade,
    HorarioNaoDefinido,
    criar_bloqueio_previo,
)


def _proxima_segunda() -> date:
    """Próxima segunda-feira estritamente futura (>= amanhã). Mantém os testes determinísticos sem
    cair na antecedência mínima (ADR 0025): um dia inteiro à frente > now + buffer. weekday(): seg=0."""
    hoje = date.today()
    dias = (7 - hoje.weekday()) % 7 or 7
    return hoje + timedelta(days=dias)


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
    """Conn fake: serve as regras de modelo_disponibilidade e registra o que mais rodou.
    `vizinho=True` faz o gap-check (existe_vizinho_no_buffer) achar um vizinho dentro do buffer."""

    def __init__(self, regras: list[dict[str, Any]], *, vizinho: bool = False) -> None:
        self.regras = regras
        self.vizinho = vizinho
        self.queries: list[str] = []

    async def execute(self, query: str, params: object = None) -> _Result:
        self.queries.append(query)
        if "modelo_disponibilidade" in query:
            return _Result(self.regras)
        if "make_interval" in query:  # gap-check (existe_vizinho_no_buffer)
            return _Result([{"?column?": 1}] if self.vizinho else [])
        if "INSERT INTO barravips.bloqueios" in query:
            return _Result([{"id": "00000000-0000-0000-0000-00000000000b"}])
        return _Result([])


# Regra: segundas (DOW Postgres = 1), 14h-18h, período aberto desde 2020 (cobre qualquer segunda futura).
_REGRA_SEGUNDA_TARDE = {
    "data_inicio": date(2020, 1, 1),
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
            atendimento=_atendimento(time(21, 0), data=_proxima_segunda()),
        )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q] == []


async def test_inicio_dentro_da_disponibilidade_reserva_normalmente():
    # Gate valida só o INÍCIO (ADR 0005): 17h cabe na janela 14h-18h mesmo que o fim (18h) a
    # encoste; o INSERT acontece. Segunda futura -> passa também na antecedência mínima (ADR 0025).
    conn = _Conn([_REGRA_SEGUNDA_TARDE])
    await criar_bloqueio_previo(
        conn,  # type: ignore[arg-type]
        atendimento=_atendimento(time(17, 0), data=_proxima_segunda()),
    )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q]


async def test_modelo_sem_regra_segue_sempre_reservavel():
    # CONTEXT.md "Disponibilidade": modelo sem nenhuma regra é reservável sempre.
    conn = _Conn([])
    await criar_bloqueio_previo(
        conn,  # type: ignore[arg-type]
        atendimento=_atendimento(time(3, 0), data=_proxima_segunda()),
    )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q]


async def test_antecedencia_insuficiente_levanta_recuperavel():
    # ADR 0025: a IA nunca reserva dentro do buffer de preparo a partir de agora. Data no passado
    # (1 ano atrás) -> inicio < now + buffer -> AntecedenciaInsuficiente, sem INSERT. Sem regra de
    # disponibilidade pra isolar a antecedência (modelo sem regra é sempre disponível).
    conn = _Conn([])
    ontem_distante = date.today() - timedelta(days=365)
    with pytest.raises(AntecedenciaInsuficiente):
        await criar_bloqueio_previo(
            conn,  # type: ignore[arg-type]
            atendimento=_atendimento(time(17, 0), data=ontem_distante),
        )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q] == []


async def test_gap_com_vizinho_no_buffer_levanta_conflito():
    # ADR 0025: vizinho ativo dentro do buffer -> ConflitoAgenda (a tool reoferta). Segunda futura
    # (passa disponibilidade + antecedência); o gap-check acha vizinho (vizinho=True), sem INSERT.
    conn = _Conn([_REGRA_SEGUNDA_TARDE], vizinho=True)
    with pytest.raises(ConflitoAgenda):
        await criar_bloqueio_previo(
            conn,  # type: ignore[arg-type]
            atendimento=_atendimento(time(17, 0), data=_proxima_segunda()),
        )
    assert [q for q in conn.queries if "INSERT INTO barravips.bloqueios" in q] == []
