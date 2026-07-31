"""O enquadramento do vídeo tem onde caber (issue 14 do refactor do prompt).

O `<midia>` mandava três coisas que não fechavam: o book sai de uma vez (fotos + vídeo no MESMO
turno), a legenda das mídias fica VAZIA, e o vídeo vai "enquadrado como exclusividade". Como o
enquadramento é texto e a legenda é vazia, não estava dito onde ele sai — e o modelo ou mandava o
vídeo cru (perdendo o argumento que o protege de ser lido como acervo) ou preenchia a legenda
(duplicando a linha no cliente, que é o bug de prod que a legenda vazia fechou).

Depois do ticket: o enquadramento mora na BOLHA, junto da linha que acompanha o book, e a legenda
continua vazia. Sem DB e sem crédito: lê o prefixo geral pelo caminho real (`render_prefixo_geral`).
"""

import re

from barra.agente.ferramentas.midia import _DESC_LEGENDA
from barra.agente.persona import render_prefixo_geral


def _bloco(nome: str) -> str:
    """O corpo de um bloco da conduta, ancorado em INÍCIO DE LINHA (os blocos se citam por nome no
    meio do texto e um casamento solto engoliria o vizinho)."""
    texto = render_prefixo_geral()
    achado = re.search(rf"^<{nome}>$(.*?)^</{nome}>$", texto, re.S | re.M)
    assert achado is not None, f"bloco <{nome}> sumiu do BP_GERAL"
    return achado.group(1)


def test_a_bolha_unica_e_quem_enquadra_o_video() -> None:
    midia = _bloco("midia")

    # A linha que acompanha o book é UMA, e é ela que carrega o enquadramento.
    assert "uma linha sua numa bolha" in midia
    assert "enquadra o vídeo como exclusividade" in midia
    # E o parágrafo do vídeo aponta pra ela em vez de pedir um texto que não tem onde sair.
    assert "quem o enquadra como exclusividade é aquela linha da bolha" in midia


def test_a_legenda_continua_vazia_nos_dois_sites() -> None:
    midia = _bloco("midia")

    # A regra que nasceu de duplicação real em prod (bolha + caption com a mesma frase).
    assert "A legenda das mídias fica vazia" in midia
    assert "o enquadramento sai na bolha, nunca na legenda" in midia
    # O eco de mecânica de campo (a DESC do arg `legenda`, lida no MESMO turno) não pode convidar
    # a preencher o que a conduta manda deixar vazio.
    assert "Deixe de fora" in _DESC_LEGENDA
    assert "BOLHA" in _DESC_LEGENDA


def test_o_video_vai_no_mesmo_turno_sem_virar_acervo_nem_ganhar_data() -> None:
    midia = _bloco("midia")

    # "degrau seguinte" contradizia o "mais de uma vez no mesmo turno" do book.
    assert "vai no mesmo turno, depois das fotos" in midia
    assert "degrau seguinte" not in midia
    # As duas regras de produto que sobrevivem intactas (CONTEXT.md, Mídia exclusiva).
    assert "nunca revela que é acervo" in midia
    assert "quando gravou não recebe data" in midia
