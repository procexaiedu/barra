"""Relogio e agenda do cenario, offline: as formas relativas da fixture e a propagacao do `agora`.

Tres coisas que nao precisam de banco e que, sem teste, quebram calado:

1. `instante_do_cenario` / `data_do_cenario` — "hoje 21:00" tem de virar 21:00 em BRT, nao em UTC
   (3h de erro, e dia trocado nas bordas da noite: 22:00 BRT = 01:00 UTC do dia seguinte).
2. `relogio_do_turno` — sem ancora declarada continua `None` (relogio de parede, o comportamento de
   todos os cenarios anteriores); com ancora, avanca de forma determinista.
3. A ARMADILHA do `rodar_e2e` (memoria `rig_relogio_injetado_finge_7_dias`): o `agora` tem de ir ao
   `seedar` E a cada turno. Ancorar so um lado faz o historico nascer no `now()` do banco enquanto o
   turno acontece no relogio fixo, e a distancia vira `<tempo_desde_ultima_msg_cliente>` fantasma +
   marca de pausa sintetica (`_GAP_PAUSA`) numa conversa que nunca teve pausa. Aqui isso e pego sem
   banco: o seed e o turno sao capturados e comparados (o efeito no prompt, com DB real, esta em
   tests/agente/test_e2e_relogio_e_bloqueios.py).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from evals.e2e import runner as runner_mod
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import relogio_do_turno, rodar_e2e
from evals.harness import Cenario, ResultadoTurno, data_do_cenario, instante_do_cenario

_BRT = ZoneInfo("America/Sao_Paulo")
# 13/08/2026 14:00 BRT = 17:00 UTC. Fixa: o teste nao pode depender de quando roda.
_AGORA = datetime(2026, 8, 13, 17, 0, tzinfo=UTC)


# --- formas relativas do cenario -------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("21:00", datetime(2026, 8, 13, 21, 0, tzinfo=_BRT)),
        ("hoje 21:00", datetime(2026, 8, 13, 21, 0, tzinfo=_BRT)),
        ("amanha 00:30", datetime(2026, 8, 14, 0, 30, tzinfo=_BRT)),
        ("amanhã 00:30", datetime(2026, 8, 14, 0, 30, tzinfo=_BRT)),
        ("ontem 23:00", datetime(2026, 8, 12, 23, 0, tzinfo=_BRT)),
        (timedelta(hours=2), datetime(2026, 8, 13, 19, 0, tzinfo=UTC)),
        (-30, datetime(2026, 8, 13, 16, 30, tzinfo=UTC)),  # bloqueio JA em curso
        (90, datetime(2026, 8, 13, 18, 30, tzinfo=UTC)),
        ("2026-09-01T21:00:00-03:00", datetime(2026, 9, 1, 21, 0, tzinfo=_BRT)),
    ],
)
def test_instante_do_cenario_resolve_as_formas_da_fixture(valor: Any, esperado: datetime) -> None:
    assert instante_do_cenario(valor, _AGORA) == esperado


def test_instante_relativo_usa_o_fuso_da_agenda_nao_utc() -> None:
    """22:00 BRT com ancora as 23:00 BRT: em UTC o dia ja virou (02:00 do dia seguinte). Se a
    resolucao fosse em UTC, "hoje 22:00" cairia no dia 14 e o cenario mediria outra noite."""
    ancora = datetime(2026, 8, 13, 23, 0, tzinfo=_BRT)
    assert instante_do_cenario("hoje 22:00", ancora) == datetime(2026, 8, 13, 22, 0, tzinfo=_BRT)
    assert instante_do_cenario("amanha 00:30", ancora) == datetime(2026, 8, 14, 0, 30, tzinfo=_BRT)


def test_instante_de_datetime_naive_vira_utc() -> None:
    """Mesma convencao do `prepare_context` (`agora_utc` sem tzinfo -> UTC)."""
    assert instante_do_cenario(datetime(2026, 8, 13, 19, 0), _AGORA) == datetime(
        2026, 8, 13, 19, 0, tzinfo=UTC
    )


@pytest.mark.parametrize("valor", ["daqui a pouco", "25h", True])
def test_instante_invalido_falha_alto(valor: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        instante_do_cenario(valor, _AGORA)


def test_data_do_cenario() -> None:
    assert data_do_cenario(None, _AGORA) is None
    assert data_do_cenario("hoje", _AGORA) == date(2026, 8, 13)
    assert data_do_cenario("amanha", _AGORA) == date(2026, 8, 14)
    assert data_do_cenario(date(2026, 12, 25), _AGORA) == date(2026, 12, 25)
    assert data_do_cenario("2026-12-25", _AGORA) == date(2026, 12, 25)
    # 23:00 BRT = 02:00 UTC do dia seguinte: o dia do cenario e o dia DELA, nao o do UTC.
    assert data_do_cenario("hoje", datetime(2026, 8, 13, 23, 0, tzinfo=_BRT)) == date(2026, 8, 13)


# --- relogio por turno -----------------------------------------------------------------------


def test_sem_ancora_o_relogio_segue_de_parede() -> None:
    """Compatibilidade: os cenarios que nao declaram `agora` continuam com `None` ponta a ponta."""
    assert relogio_do_turno(None, 0) is None
    assert relogio_do_turno(None, 5, passo_min=10) is None


def test_passo_constante_e_offsets_por_turno() -> None:
    assert relogio_do_turno(_AGORA, 0, passo_min=10) == _AGORA
    assert relogio_do_turno(_AGORA, 3, passo_min=10) == _AGORA + timedelta(minutes=30)
    # offsets vencem o passo e repetem o ultimo quando a conversa passa do roteiro declarado
    offsets = [0, 5, 30]
    assert relogio_do_turno(_AGORA, 2, passo_min=10, offsets_min=offsets) == _AGORA + timedelta(
        minutes=30
    )
    assert relogio_do_turno(_AGORA, 9, offsets_min=offsets) == _AGORA + timedelta(minutes=30)


# --- a armadilha: o `agora` tem de ir aos DOIS lados -----------------------------------------


def _resultado_turno() -> ResultadoTurno:
    return ResultadoTurno(
        texto="ok",
        tool_calls=[],
        tool_args=[],
        nodes=[],
        prompt_modelo=[],
        mensagens=[],
        estado_final={"estado": "Triagem", "ia_pausada": False},
    )


class _EspiaoDoRelogio:
    """Captura o `agora` que o runner passou ao seed e a cada turno, sem tocar no banco."""

    def __init__(self) -> None:
        self.seed: list[datetime | None] = []
        self.turnos: list[datetime | None] = []
        self.fixtures: list[dict[str, Any]] = []

    async def seedar(
        self, conn: Any, fixture: dict[str, Any], *, agora: datetime | None = None
    ) -> Cenario:
        self.seed.append(agora)
        self.fixtures.append(fixture)
        from uuid import uuid4

        return Cenario(
            cliente_id=uuid4(),
            modelo_id=uuid4(),
            conversa_id=uuid4(),
            atendimento_id=uuid4(),
            agora=agora,
        )

    async def rodar_turno_auditado(
        self, conn: Any, cen: Cenario, turno: Any, *, graph: Any = None, agora: Any = None
    ) -> ResultadoTurno:
        self.turnos.append(agora)
        return _resultado_turno()


@pytest.fixture
def espiao(monkeypatch: pytest.MonkeyPatch) -> _EspiaoDoRelogio:
    esp = _EspiaoDoRelogio()
    monkeypatch.setattr(runner_mod, "seedar", esp.seedar)
    monkeypatch.setattr(runner_mod, "rodar_turno_auditado", esp.rodar_turno_auditado)
    return esp


def _perfil() -> PerfilCaso:
    return PerfilCaso(nome="relogio", abertura="oi", modelo={}, roteiro_cliente=["e ai", "fechado"])


async def test_ancora_vai_ao_seed_e_a_todos_os_turnos(espiao: _EspiaoDoRelogio) -> None:
    """A armadilha documentada: ancorar so o turno (seed no `now()` do banco) fabrica tempo
    decorrido e marca de pausa. Aqui o seed tem de sair no MESMO instante do turno 1."""
    await rodar_e2e(
        None,  # type: ignore[arg-type]
        _perfil(),
        ClienteRoteirizado(["e ai", "fechado"]),
        max_turnos=3,
        agora=_AGORA,
        passo_min=5,
    )
    assert espiao.seed == [_AGORA]
    assert espiao.turnos == [_AGORA, _AGORA + timedelta(minutes=5), _AGORA + timedelta(minutes=10)]


async def test_offsets_por_turno_movem_o_seed_junto(espiao: _EspiaoDoRelogio) -> None:
    """Com offset no primeiro turno, o seed acompanha — senao o historico nasce ATRAS do turno 1."""
    await rodar_e2e(
        None,  # type: ignore[arg-type]
        _perfil(),
        ClienteRoteirizado(["e ai", "fechado"]),
        max_turnos=3,
        agora=_AGORA,
        offsets_min=[0, 0, 25],
    )
    assert espiao.seed == [_AGORA]
    assert espiao.turnos == [_AGORA, _AGORA, _AGORA + timedelta(minutes=25)]


async def test_sem_agora_nada_muda_para_os_cenarios_existentes(espiao: _EspiaoDoRelogio) -> None:
    """Compatibilidade dos 22 cenarios: sem as chaves novas, seed e turnos seguem em `None` e a
    fixture sai identica a que o `perfil_para_fixture` monta (sem `bloqueios`)."""
    await rodar_e2e(
        None,  # type: ignore[arg-type]
        _perfil(),
        ClienteRoteirizado(["e ai"]),
        max_turnos=2,
    )
    assert espiao.seed == [None]
    assert espiao.turnos == [None, None]
    assert espiao.fixtures[0] == {
        "cenario": {"modelo": {}, "atendimento": {"estado": "Novo"}},
        "historico": [],
    }


async def test_bloqueios_e_atendimento_entram_na_fixture(espiao: _EspiaoDoRelogio) -> None:
    """G-INS-1/G-INS-3 pela porta do runner: a agenda ocupada e o atendimento ja marcado chegam ao
    `seedar` sem que o cenario precise seedar a mao."""
    bloqueios = [{"inicio": timedelta(hours=3), "duracao_min": 60, "atendimento": True}]
    await rodar_e2e(
        None,  # type: ignore[arg-type]
        _perfil(),
        ClienteRoteirizado(["e ai"]),
        max_turnos=1,
        agora=_AGORA,
        bloqueios=bloqueios,
        atendimento={"estado": "Aguardando_confirmacao", "horario_desejado": "21:00"},
    )
    cenario = espiao.fixtures[0]["cenario"]
    assert cenario["bloqueios"] == bloqueios
    assert cenario["atendimento"] == {
        "estado": "Aguardando_confirmacao",
        "horario_desejado": "21:00",
    }
