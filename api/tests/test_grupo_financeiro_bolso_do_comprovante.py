"""A quarta classe de comprovante entra na tabela de evidência do bolso (ADR-0047, ticket 04).

`resolver_bolso` nasceu com as duas direções que o ADR-0047 §2 enumerou — ela transferindo pra
casa e o cliente pagando a casa. A terceira, o **cliente pagando na chave DELA** (a classe
`entrada_da_modelo` de `comprovante.py`), não tinha linha própria porque a tabela foi escrita antes
de o papel da chave existir: sem saber de quem era o destino, "o cliente pagou nela" era um palpite
sobre um nome. Com o registro tipado (ADR-0049) ela é cadastro.

O que este arquivo pina é que a linha nova **não mexe na precedência** das que já estavam lá — a
ordem da tabela é o que cada evidência prova, e é ela que decide quando duas falam ao mesmo tempo.
"""

from __future__ import annotations

from decimal import Decimal

from barra.dominio.grupo_financeiro.bolso import (
    BOLSO_NAO_DITO,
    confrontar_bolso,
    montar_pergunta_do_bolso,
    resolver_bolso,
)


def test_comprovante_do_cliente_para_a_chave_dela_resolve_o_bolso_em_dela() -> None:
    """O dinheiro caiu na conta dela sem nunca passar pela casa — o bruto ficou na mão dela.

    Mesmo resultado da primeira linha (`dela`), caminho diferente: lá ela transferiu para a casa,
    aqui o cliente pagou direto na chave dela e não há transferência nenhuma a creditar.
    """
    resolvido = resolver_bolso(comprovante_do_cliente_para_a_modelo=True)

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_modelo"
    assert resolvido.dito


def test_a_linha_nova_nao_atropela_o_comprovante_dela_para_a_casa() -> None:
    """As duas dizem `dela`, então a ordem não muda o veredito — muda a DEFESA dele.

    A evidência viaja junto do bolso porque as duas perguntas do operador diante de um saldo torto
    são "em que bolso o agente achou que caiu?" e "por quê?". O extrato do banco dela transferindo
    continua sendo a resposta mais dura, e é ela que fica registrada.
    """
    resolvido = resolver_bolso(
        comprovante_dela_para_a_casa=True, comprovante_do_cliente_para_a_modelo=True
    )

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "comprovante_dela_para_a_casa"


def test_a_linha_nova_vence_a_fala_e_a_forma_como_toda_evidencia_de_imagem() -> None:
    """Comprovante é extrato de banco; fala é humana e pode ser engano de quem digitou."""
    resolvido = resolver_bolso(
        comprovante_do_cliente_para_a_modelo=True, fala="empresa", forma="pix"
    )

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_modelo"


def test_o_cliente_pagando_a_casa_continua_desmentindo_o_que_a_fala_disser() -> None:
    """A regressão que a linha nova poderia ter causado: empurrar a linha de `empresa` para baixo
    da fala faria "ficou comigo" vencer o extrato que prova o contrário."""
    resolvido = resolver_bolso(comprovante_do_cliente_para_a_casa=True, fala="dela")

    assert resolvido.bolso == "empresa"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_casa"


def test_a_pergunta_diz_qual_comprovante_a_motivou() -> None:
    """Sem a oração da evidência, a pergunta seria "de qual bolso?" sem dizer o que a motivou — e
    quem lê não teria como saber se o agente entendeu a foto certa."""
    mudanca = confrontar_bolso("empresa", resolver_bolso(comprovante_do_cliente_para_a_modelo=True))

    assert mudanca.conduta == "perguntar"
    pergunta = montar_pergunta_do_bolso(mudanca, valor=Decimal("600.00"), cliente_nome="Ramon")
    assert "o comprovante é o cliente pagando na chave dela" in pergunta


def test_nada_muda_para_quem_nao_passa_a_linha_nova() -> None:
    """O parâmetro é opcional e o default é o silêncio: todo chamador de antes do ticket 04
    continua lendo a mesma tabela."""
    assert resolver_bolso().bolso == BOLSO_NAO_DITO
    assert resolver_bolso(forma="dinheiro").evidencia == "especie"
