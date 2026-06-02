"""Aceite CUSTO-02: custo de vision (Pix) e STT (Whisper) por chamada, e soma por atendimento.

Funcoes puras testaveis offline (sem provider): a tabela de preco de vision espelha o Sonnet,
o STT e por-minuto, e custo_por_atendimento_brl soma chat+STT+vision. As tarifas sao defaults
PENDENTES de confirmacao do operador (ver docstring de _custo.py).
"""

from dataclasses import dataclass

import pytest

from barra.agente._custo import (
    PRECO_VISION_USD_PER_MTOK,
    TARIFA_STT_USD_POR_MINUTO,
    calcular_custo_stt_brl,
    calcular_custo_vision_brl,
    custo_por_atendimento_brl,
)

COTACAO = 5.50


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


def test_vision_combina_prompt_e_completion() -> None:
    # prompt=2k, completion=300. USD = 2k*3/1M + 300*15/1M = 0.006 + 0.0045 = 0.0105 USD.
    usage = _FakeUsage(prompt_tokens=2000, completion_tokens=300)
    esperado_usd = (
        2000 * PRECO_VISION_USD_PER_MTOK["input"]
        + 300 * PRECO_VISION_USD_PER_MTOK["output"]
    ) / 1_000_000
    assert calcular_custo_vision_brl(usage, COTACAO) == pytest.approx(esperado_usd * COTACAO)


def test_vision_usage_none_devolve_zero() -> None:
    # Resposta inconclusiva / fake sem usage -> 0.0 (mesma defesa do chat).
    assert calcular_custo_vision_brl(None, COTACAO) == 0.0


def test_vision_atributos_faltando_tratados_como_zero() -> None:
    # Usage sem completion_tokens (getattr default 0): so conta o prompt.
    @dataclass
    class _So:
        prompt_tokens: int

    custo = calcular_custo_vision_brl(_So(prompt_tokens=1000), COTACAO)
    assert custo == pytest.approx(1000 * PRECO_VISION_USD_PER_MTOK["input"] / 1_000_000 * COTACAO)


def test_stt_por_minuto() -> None:
    # 90s = 1.5 min. USD = 1.5 * 0.006 = 0.009 USD.
    custo = calcular_custo_stt_brl(90.0, COTACAO)
    assert custo == pytest.approx(1.5 * TARIFA_STT_USD_POR_MINUTO * COTACAO)


def test_stt_duracao_zero_ou_negativa_devolve_zero() -> None:
    # Audio nao medido (duration ausente -> 0.0) nao gera custo nem divide errado.
    assert calcular_custo_stt_brl(0.0, COTACAO) == 0.0
    assert calcular_custo_stt_brl(-5.0, COTACAO) == 0.0


def test_custo_por_atendimento_soma_tres_componentes() -> None:
    # Soma simples: chat + STT + vision.
    assert custo_por_atendimento_brl(0.10, 0.01, 0.05) == pytest.approx(0.16)


def test_custo_por_atendimento_so_chat() -> None:
    # Atendimento so de texto (sem audio nem Pix) = so o custo de chat.
    assert custo_por_atendimento_brl(0.12, 0.0, 0.0) == pytest.approx(0.12)
