"""`registrar_extracao` desambigua `AntecedenciaInsuficiente` pelo `horario_minimo` do State.

Regressão do bug de borda (rig 2026-06-25): pedido "agora" perto do fim do expediente. O domínio
levanta `AntecedenciaInsuficiente` (o horário PEDIDO ainda está dentro da Disponibilidade, mas é
< now+buffer). Quando `horario_minimo` é None (now+buffer já passou do fim da janela), NÃO há
horário válido mais tarde hoje: mandar "ofereça o <horario_minimo>" apontaria pra uma tag ausente e
a IA inventaria um horário fora da janela (ela ofereceu "23h20" com expediente até 23h). A tool deve
cair na conduta de período de trabalho. Com `horario_minimo` presente, segue a conduta de preparo.

Unit, sem DB: monkeypatcha `_executar_idempotente` p/ levantar a exceção antes de tocar o banco;
o pool fake só prova que a tool abre/fecha a conexão. Mede o DELTA do counter (registry global).
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import ToolException
from prometheus_client import REGISTRY

import barra.agente.ferramentas.extracao as extracao_mod
from barra.agente.ferramentas.extracao import registrar_extracao
from barra.dominio.agenda.service import AntecedenciaInsuficiente

BRT = ZoneInfo("America/Sao_Paulo")

# .coroutine = corrotina crua do @tool; injeta `runtime` (.ainvoke({...}) não).
_chamar = registrar_extracao.coroutine  # type: ignore[attr-defined]


class _FakeConn:
    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakeConn:
        return _FakeConn()


class _Ctx:
    db_pool = _FakePool()
    atendimento_id = "00000000-0000-0000-0000-000000000001"
    turno_id = "00000000-0000-0000-0000-000000000002"
    agora_utc = None


class _Runtime:
    def __init__(self, state: dict[str, Any]) -> None:
        self.context = _Ctx()
        self.state = state


async def _forcar_antecedencia(*_a: Any, **_k: Any) -> Any:
    raise AntecedenciaInsuficiente("cedo demais (now + buffer)")


def _valor() -> float:
    valor = REGISTRY.get_sample_value(
        "agente_tool_erro_recuperavel_total",
        {"tool": "registrar_extracao", "motivo": "antecedencia_insuficiente"},
    )
    return valor or 0.0


async def test_horario_minimo_none_cai_em_periodo_de_trabalho(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`horario_minimo` None: conduta de período de trabalho, NUNCA ancorar no <horario_minimo>."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    antes = _valor()
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": None}),
        )
    msg = str(exc.value)
    assert msg.startswith("ERRO:")
    assert "período de trabalho" in msg
    assert "<periodo_de_trabalho>" in msg
    # NÃO manda ancorar num horario_minimo que não existe (era o bug).
    assert "<horario_minimo>" not in msg
    # E NÃO importa o pressuposto falso "está de folga" (o None pode vir de bloqueio).
    assert "folga" not in msg.lower()
    assert _valor() == antes + 1


async def test_horario_minimo_presente_mantem_conduta_de_preparo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`horario_minimo` presente: conduta de preparo, ancorando no <horario_minimo>."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    antes = _valor()
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": datetime(2026, 6, 25, 23, 30, tzinfo=BRT)}),
        )
    msg = str(exc.value)
    assert msg.startswith("ERRO:")
    assert "cedo demais" in msg
    assert "<horario_minimo>" in msg
    assert _valor() == antes + 1


async def test_state_sem_a_chave_degrada_para_periodo_de_trabalho(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.get` ausente (state vazio) → None → fallback seguro (período de trabalho), sem KeyError."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({}),
        )
    assert "período de trabalho" in str(exc.value)
