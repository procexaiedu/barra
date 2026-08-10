"""O eixo `conduta` do judge pós-envio vira série Prometheus (alerta ativo).

Antes disso a nota de conduta só existia em `julgamentos_turno` e ninguém a consumia: conduta ruim
levava horas/dias pra ser percebida. `agente_judge_conduta_total{faixa}` é o que a regra
`AgenteCondutaReprovada` lê. Reusa o FakeConn/FakePool de test_judge_pos_envio (mesmo alvo, sem
DB nem DeepSeek reais).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from prometheus_client import REGISTRY
from tests.test_judge_pos_envio import CONVERSA, FakeConn, _ctx, _veredito

from barra.workers import judge_pos_envio


def _faixa(nome: str) -> float:
    # Gotcha: `get_sample_value` NAO duplica o sufixo `_total` — o nome da amostra de um
    # Counter("agente_judge_conduta_total") é exatamente esse.
    return REGISTRY.get_sample_value("agente_judge_conduta_total", {"faixa": nome}) or 0.0


def _julgar(monkeypatch: pytest.MonkeyPatch, conduta: int) -> None:
    conn = FakeConn()

    async def _fake(*_: Any, **__: Any) -> Any:
        return _veredito(conduta=conduta)

    monkeypatch.setattr(judge_pos_envio, "_julgar", _fake)
    resultado = asyncio.run(
        judge_pos_envio.julgar_turno_pos_envio(
            _ctx(conn), conversa_id=CONVERSA, turno_id=f"t-conduta-{conduta}:0", chunks=["oi amor"]
        )
    )
    assert resultado == 1


@pytest.mark.parametrize("conduta", [1, 2])
def test_conduta_baixa_conta_como_reprovada(monkeypatch: pytest.MonkeyPatch, conduta: int) -> None:
    antes_reprovada, antes_ok = _faixa("reprovada"), _faixa("ok")

    _julgar(monkeypatch, conduta)

    assert _faixa("reprovada") == antes_reprovada + 1
    assert _faixa("ok") == antes_ok


@pytest.mark.parametrize("conduta", [3, 4, 5])
def test_conduta_aceitavel_conta_como_ok(monkeypatch: pytest.MonkeyPatch, conduta: int) -> None:
    antes_reprovada, antes_ok = _faixa("reprovada"), _faixa("ok")

    _julgar(monkeypatch, conduta)

    assert _faixa("ok") == antes_ok + 1
    assert _faixa("reprovada") == antes_reprovada


def test_turno_nao_julgado_nao_gera_serie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Judge indisponível (sem veredito) não pode inventar faixa — senão a taxa do alerta
    passaria a medir a saúde do judge em vez da conduta da IA."""
    antes_reprovada, antes_ok = _faixa("reprovada"), _faixa("ok")
    conn = FakeConn()

    async def _explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("judge fora")

    monkeypatch.setattr(judge_pos_envio, "_julgar", _explode)
    assert (
        asyncio.run(
            judge_pos_envio.julgar_turno_pos_envio(
                _ctx(conn), conversa_id=CONVERSA, turno_id="t-indisp:0", chunks=["oi"]
            )
        )
        == 0
    )

    assert (_faixa("reprovada"), _faixa("ok")) == (antes_reprovada, antes_ok)
