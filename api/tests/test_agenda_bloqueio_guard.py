"""Regressão (achado real do 1º baseline do flywheel): `criar_bloqueio_previo` SEM `horario_desejado`
levanta `HorarioNaoDefinido` (erro recuperável que a tool de Pix converte em instrução p/ a IA),
NUNCA o `TypeError` cru de `datetime.combine(data, None)` que crashava o turno quando o cliente pedia
o Pix de deslocamento antes de cravar a hora. PURO: o guard dispara ANTES de qualquer uso da conexão.
"""

import pytest

from barra.dominio.agenda.service import HorarioNaoDefinido, criar_bloqueio_previo


def _atendimento(horario):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "modelo_id": "00000000-0000-0000-0000-000000000002",
        "data_desejada": None,
        "horario_desejado": horario,
        "duracao_horas": 1,
    }


async def test_sem_horario_levanta_recuperavel_nao_typeerror():
    # conn=None de propósito: o guard de horário ausente dispara ANTES de qualquer conn.execute,
    # então não precisa de banco. Antes do fix isto era um TypeError em datetime.combine(data, None).
    with pytest.raises(HorarioNaoDefinido):
        await criar_bloqueio_previo(None, atendimento=_atendimento(None))  # type: ignore[arg-type]
