"""Dois achados do replay sobre a LEITURA do anuncio (14/08/2026), com sinais opostos.

**A duracao colada no valor.** O anuncio dizia "900 1h30" e o agente respondia "❓ Só falta saber:
quanto foi o atendimento do Cliente Henrique?" — com o valor escrito na mensagem. A causa e a
ancora `$` da regex do valor, que decide tudo-ou-nada: faltando o "min" que ela exigia depois dos
minutos, a linha inteira deixava de casar, e com ela o 900. Um erro de leitura de DURACAO virava
um erro de leitura de VALOR, que e o campo que vira dinheiro.

**A triagem de uma linha so.** No outro sentido, "Cliente chato esse hein" — conversa — passava na
triagem e virava um anuncio pela metade, esperando um valor que o proximo numero solto do grupo
completaria.

Os dois sao o mesmo tipo de erro visto de lados diferentes: a fronteira entre o que e anuncio e o
que e conversa e onde este modulo escreve dinheiro.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from barra.dominio.grupo_financeiro.anuncio import (
    extrair_anuncio,
    ler_valor_avulso,
    parece_anuncio_de_venda,
)

ANUNCIO = "Atendimento no nosso local\nCliente Henrique\nPerfil mel\n{cauda}"


@pytest.mark.parametrize(
    ("cauda", "valor", "minutos"),
    [
        ("900 1h30", Decimal("900.00"), 90),  # a grafia dominante da hora e meia
        ("900 1h30min", Decimal("900.00"), 90),  # a unica que passava antes
        ("900 1h", Decimal("900.00"), 60),
        ("900 2h", Decimal("900.00"), 120),
        ("900 30min", Decimal("900.00"), 30),
        ("900", Decimal("900.00"), None),  # duracao e opcional; valor nao
        ("R$ 1.300,00 1h30", Decimal("1300.00"), 90),
    ],
)
def test_valor_sobrevive_a_duracao_colada(cauda: str, valor: Decimal, minutos: int | None) -> None:
    lido = extrair_anuncio(ANUNCIO.format(cauda=cauda))
    assert lido.valor == valor
    assert lido.duracao_minutos == minutos


def test_duracao_solta_na_linha_do_atendimento_tambem_le_a_meia_hora() -> None:
    """ "Atendimento de 1h30" e a mesma grafia na outra posicao — a do export real ("de 2h")."""
    lido = extrair_anuncio("Atendimento de 1h30\nCliente Igor\nPerfil mel\n600")
    assert lido.duracao_minutos == 90
    assert lido.local is None  # "de 1h30" e duracao, nao endereco


def test_a_resposta_da_pergunta_minima_aceita_a_mesma_grafia() -> None:
    """O grupo responde "600 1h30" a pergunta minima — mesmo parser, mesmo direito."""
    assert ler_valor_avulso("600 1h30") == (Decimal("600.00"), 90)


@pytest.mark.parametrize("linha", ["Torre 2 Apt 1102", "600 pix", "sao 3 dias", "1h30"])
def test_o_que_nao_e_valor_continua_nao_sendo(linha: str) -> None:
    """A abertura foi na DURACAO, nao no valor: numero de apartamento nao virou dinheiro."""
    assert ler_valor_avulso(linha) is None


# --- a triagem: uma linha com marcador nao e anuncio ---------------------------------------------


@pytest.mark.parametrize(
    "conversa",
    [
        "Cliente chato esse hein",  # a linha que fez o agente perguntar o preco de uma piada
        "Cliente novo chegando amanhã",
        "atendimento cancelado amiga",
        "Perfil bianca/yasmin",
        "Cliente pediu pra remarcar",
    ],
)
def test_conversa_que_comeca_com_marcador_nao_e_anuncio(conversa: str) -> None:
    """Uma linha so nunca e anuncio — e o fantasma que essa linha criava era perigoso.

    O anuncio incompleto fica esperando o valor: com "Cliente chato esse hein" registrado como
    anuncio pela metade, o proximo "600" solto do grupo (a resposta da pergunta minima de OUTRA
    venda) completaria uma venda que nunca existiu.
    """
    assert parece_anuncio_de_venda(conversa) is False


@pytest.mark.parametrize(
    "anuncio",
    [
        "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h",
        "Atendimento no nosso local \nCliente Antônio\nSeu nome é bianca \n600 1h",
        "Atendimento de 2h\nCliente Igor  e um amigo\nPerfil bianca/yasmin\n1300 cada uma",
        "Atendimento no nosso local\nCliente Diego\nPerfil sasa",  # incompleto: pergunta minima
        "Cliente Gabriel\n700",  # a forma curta: um marcador + o valor em linha propria
    ],
)
def test_o_anuncio_real_continua_passando(anuncio: str) -> None:
    assert parece_anuncio_de_venda(anuncio) is True
