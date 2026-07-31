"""A fala ilustrativa do incluso tem um site só na conduta (issue 18 do refactor do prompt).

O molde da apresentação ("Sou bem tranquila" / "Estilo namoradinha" / o item incluso) vivia inline
no `<apresentacao>` E como diálogo no `<exemplo>` de abertura+cotação+apresentação — duas cópias da
MESMA string no prefixo cacheado, dobrando a pressão de cópia sobre exatamente a fala que vazou em
prod com o `<fetiches>` vazio. Depois do ticket: o molde é o `<exemplo>`, e o `<apresentacao>`
aponta para ele sem repeti-lo; a regra dele (os SEUS itens saem nominalmente da linha "Inclusos")
ficou.

Por que a cópia que saiu foi a do `<apresentacao>`, e não a do `<exemplo>`: o guard
`bolhas_incluso_fantasma` (issue 07) só enxerga quem DECLARA incluso ("tá incluso", "já vem
junto"). A bolha do `<exemplo>` declara — tem rede. A do `<apresentacao>` era uma lista de itens
sem verbo, a única forma que o guard não vê. Tirar a que não tinha rede é o lado seguro do corte;
o último teste daqui congela essa assimetria, que é o que licencia a deleção.

Sem DB e sem crédito: lê o prefixo geral pelo caminho real (`render_prefixo_geral`).
"""

import re

from barra.agente.nos.output_guard import bolhas_incluso_fantasma
from barra.agente.persona import render_prefixo_geral

# A bolha de incluso do `<exemplo>` de apresentação — o molde que SOBREVIVE.
_MOLDE_DO_EXEMPLO = "Beijo no pescoço e carinho sem pressa tá incluso amor"
# A cópia inline que saiu do `<apresentacao>`: lista de itens, sem o verbo do claim.
_COPIA_RETIRADA = "Beijo no pescoço, carinho sem pressa 🥰"


def _bloco(nome: str) -> str:
    """O corpo de um bloco da conduta, ancorado em início de linha (os blocos se citam por nome no
    meio do texto, e um casamento solto começaria na citação)."""
    achado = re.search(rf"^<{nome}>$(.*?)^</{nome}>$", render_prefixo_geral(), re.S | re.M)
    assert achado is not None, f"bloco <{nome}> sumiu do BP_GERAL"
    return achado.group(1)


def test_a_apresentacao_aponta_para_o_exemplo_em_vez_de_repetir_a_fala() -> None:
    apresentacao = _bloco("apresentacao")

    assert _COPIA_RETIRADA not in apresentacao
    assert "carinho sem pressa" not in apresentacao, (
        "a fala ilustrativa do incluso voltou a existir 2x no BP_GERAL — o molde é o <exemplo>"
    )
    assert "o molde é o <exemplo> de apresentação" in apresentacao


def test_a_apresentacao_continua_prescrevendo_estilo_mais_incluso_do_bloco_dela() -> None:
    apresentacao = _bloco("apresentacao")

    # A forma (o que entra, em quantas bolhas) e o gate por item, que é o que o corte NÃO podia levar.
    assert "seu estilo e o que está incluso, em 2-3 bolhas curtas" in apresentacao
    assert 'os seus saem nominalmente da linha "Inclusos" do seu <fetiches>' in apresentacao


def test_o_molde_sobrevive_no_exemplo() -> None:
    prefixo = render_prefixo_geral()

    assert _MOLDE_DO_EXEMPLO in prefixo
    # Uma vez só: o preâmbulo de <exemplos> NOMEIA os itens, não repete a fala. (O par de
    # `persona.md` <armadilhas_de_voz> traz uma variante próxima, terminada em 🥰 — ela fica de
    # propósito, e por declarar incluso tem a rede do guard. Ver o ticket 18.)
    assert prefixo.count(_MOLDE_DO_EXEMPLO) == 1


def test_o_lado_do_corte_e_o_que_o_guard_nao_ve() -> None:
    """A assimetria que licencia a deleção: a cópia que ficou tem rede, a que saiu não tinha."""
    assert bolhas_incluso_fantasma(_MOLDE_DO_EXEMPLO, set())
    assert not bolhas_incluso_fantasma(_COPIA_RETIRADA, set())
