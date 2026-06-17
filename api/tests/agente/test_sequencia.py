"""Teste do validador de ordem (`evals.sequencia`) — puro, sem DB e sem credito.

Monta `ResultadoE2E` sinteticos (so os campos que o validador le) e cobre as duas regras v1 +
o caso de cotar-e-confirmar-no-mesmo-turno (nao deve violar). Roda na suite padrao (`make test`).
"""

from __future__ import annotations

from typing import Any

from evals.e2e.runner import ResultadoE2E
from evals.harness import ResultadoTurno
from evals.sequencia import avaliar_sequencia


def _turno(
    *,
    estado: str,
    pix_status: str = "nao_solicitado",
    tool_calls: list[str] | None = None,
    tool_args: list[dict[str, Any]] | None = None,
) -> ResultadoTurno:
    return ResultadoTurno(
        texto="",
        tool_calls=tool_calls or [],
        tool_args=tool_args or [],
        nodes=[],
        prompt_modelo=[],
        mensagens=[],
        estado_final={"estado": estado, "pix_status": pix_status, "ia_pausada": False},
    )


def _res(turnos: list[ResultadoTurno]) -> ResultadoE2E:
    return ResultadoE2E(
        perfil_nome="teste",
        trajetoria=[t.estado_final for t in turnos],
        turnos=turnos,
    )


def test_cota_depois_confirma_passa() -> None:
    """Cotou num turno e confirmou em turno posterior: sequencia valida."""
    res = _res(
        [
            _turno(
                estado="Qualificado",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True}],
            ),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


def test_cota_e_confirma_no_mesmo_turno_passa() -> None:
    """Cotacao e transicao no MESMO turno: a extracao precede a transicao, nao viola."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "interno"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


def test_confirma_sem_cotar_viola() -> None:
    """R1: chegou em Aguardando_confirmacao sem nenhum cotacao_apresentada."""
    res = _res(
        [
            _turno(estado="Qualificado", tool_calls=["registrar_extracao"], tool_args=[{}]),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ]
    )
    falhas = avaliar_sequencia(res)
    assert len(falhas) == 1
    assert "funil-vazamento" in falhas[0]


def test_pix_sem_externo_viola() -> None:
    """R2: pix saiu de nao_solicitado sem tipo_atendimento=externo visto antes."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                pix_status="aguardando",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "interno"}],
            ),
        ]
    )
    falhas = avaliar_sequencia(res)
    assert any("pix solicitado sem" in f for f in falhas)


def test_pix_com_externo_passa() -> None:
    """Pix apos tipo=externo: valido (e cotacao antes de confirmar)."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                pix_status="aguardando",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "externo"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []
