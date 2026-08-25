"""A validacao da resposta do leitor de intencao: o que o provider erra nao pode matar o resto.

Achado em 14/08/2026, e ele nasceu de uma MELHORIA no prompt: bastou escrever que, sem forma dita,
a resposta e "nada" para o modelo passar a preencher `"forma": "nada"` — uma palavra que o
`Literal["pix","dinheiro"]` recusa. O `ValidationError` levava junto o `tipo`, que estava certo, e
TODA mensagem negativa do grupo virava leitura perdida (medido: 13 de 27 frases).

A regra que fica: um campo que so e lido quando `tipo == "forma_de_pagamento"` nao pode ter poder
de veto sobre os outros. Mesma fronteira LLM->tool que ja custou turno neste projeto — e o mesmo
remedio do `ValorEmReais` do OCR: coagir na entrada em vez de levantar.
"""

from __future__ import annotations

import pytest

from barra.agente_financeiro.leitura import _Saida


@pytest.mark.parametrize("bruto", ["nada", "", "nenhuma", "PIX ou dinheiro", "n/a"])
def test_forma_desconhecida_vira_nulo_sem_derrubar_a_leitura(bruto: str) -> None:
    lida = _Saida.model_validate_json(
        f'{{"tipo": "nada", "forma": "{bruto}", "vendas": [], "confianca": "alta"}}'
    )
    assert lida.tipo == "nada"
    assert lida.forma is None


@pytest.mark.parametrize(("bruto", "esperado"), [("pix", "pix"), ("Dinheiro", "dinheiro")])
def test_a_forma_de_verdade_continua_passando(bruto: str, esperado: str) -> None:
    """A tolerancia e so na grafia do LIXO: pix e dinheiro seguem sendo lidos, com ou sem caixa."""
    lida = _Saida.model_validate_json(
        f'{{"tipo": "forma_de_pagamento", "forma": "{bruto}", "vendas": [0], "confianca": "alta"}}'
    )
    assert lida.forma == esperado


def test_tipo_invalido_ainda_derruba_a_leitura() -> None:
    """`tipo` NAO e tolerante, e nao deve ser: sem ele nao ha o que a porta faca com a resposta.

    A diferenca entre os dois campos e o que se perde ao aceitar lixo — em `forma`, perde-se um
    detalhe que a porta so usa num ramo; em `tipo`, perde-se a decisao inteira.
    """
    with pytest.raises(ValueError, match="tipo"):
        _Saida.model_validate_json(
            '{"tipo": "talvez", "forma": "pix", "vendas": [], "confianca": "alta"}'
        )
