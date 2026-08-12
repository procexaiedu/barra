"""Pedido de foto antes de qualquer cotação: reconhece, cota e manda o book — no MESMO turno.

O `<midia>` sempre disse que a foto é arma de fechamento e não vitrine (o book não sai sem valor
na mesa). A regra fica; o defeito era a FALA que ela produzia: "manda mais fotos" recebia
`"400 1h no meu local" / "Seria que horas ?"` — preço seco em cima de um pedido de foto, um
non sequitur que o dono do negócio leu como alucinação ("ela ignora o que ele pediu").

O gate nunca exigiu o preço num turno ANTERIOR — exige o preço na mesa. Então os dois cabem no
mesmo turno: reconhecimento + cotação + book. Este teste fixa a nova prescrição, os vizinhos que
não podiam cair junto (book nunca na saudação, nunca como prova a "é bot?", uma vez só na
negociação) e a coerência de contagem de bolhas entre o `<midia>` e o `<formato_das_bolhas>` —
prescrição em dois sites que se contradizem é o bug que este projeto trata como bug.

Sem DB e sem crédito: lê o prefixo geral pelo caminho real (`render_prefixo_geral`).
"""

import re

from barra.agente.persona import render_prefixo_geral


def _bloco(nome: str) -> str:
    """O corpo de um bloco do BP_GERAL, ancorado em INÍCIO DE LINHA (os blocos se citam por nome
    no meio do texto e um casamento solto engoliria o vizinho)."""
    texto = render_prefixo_geral()
    achado = re.search(rf"^<{nome}>$(.*?)^</{nome}>$", texto, re.S | re.M)
    assert achado is not None, f"bloco <{nome}> sumiu do BP_GERAL"
    return achado.group(1)


def test_o_midia_manda_reconhecer_cotar_e_mandar_o_book_no_mesmo_turno() -> None:
    midia = _bloco("midia")

    # A ordem é a prescrição, não uma sugestão — e o "mesmo turno" é o que mata o preço seco.
    assert "o turno reconhece o pedido, cota e manda o book, nesta ordem" in midia
    assert "não um turno anterior" in midia
    # E o diagnóstico do Fernando fica escrito: número sozinho em cima do pedido de foto responde
    # outra coisa. Sem esta linha o modelo volta a ler a regra como "cota e segura a foto".
    assert "Responder um pedido de foto só com o número" in midia
    # A prescrição antiga (a foto só num turno POSTERIOR, se ele insistisse) não pode voltar.
    assert "recebe a cotação primeiro" not in midia
    assert "se ele mantiver o pedido com o preço já cotado" not in midia


def test_o_book_continua_arma_de_fechamento_e_nao_vitrine() -> None:
    midia = _bloco("midia")

    # O que a correção NÃO afrouxa: o valor na mesa segue sendo condição do book...
    assert "Foto sua é arma de fechamento, não de vitrine" in midia
    # ...a saudação não recebe book (a proibição agora nomeia o turno de saudação, em vez de "o
    # primeiro turno" — que contradiria o pedido de foto vindo já na 1ª mensagem dele)...
    assert "nunca no primeiro turno de saudação" in midia
    assert '"oi gata, vi seu anúncio" recebe resposta e cotação, não foto' in midia
    # ...o teste de bot continua sem prova espontânea...
    assert 'nunca como resposta a "é bot?"' in midia
    assert "Queimar o book num teste de bot" in midia
    # ...e o book segue indo UMA vez na negociação, com a flag de disciplina mandando.
    assert "O book vai uma vez na negociação" in midia
    assert midia.count("<ja_enviou_book>") >= 2  # o item do book + o carve-out do turno novo


def test_o_turno_novo_cabe_no_limite_de_bolhas_da_persona() -> None:
    """As duas pontas da mesma conta, em sites diferentes: o `<formato_das_bolhas>` fixa o teto e o
    `<midia>` declara que a fala nova cabe nele. Mexer num sem o outro = contradição de prompt."""
    formato, midia = _bloco("formato_das_bolhas"), _bloco("midia")

    assert "Máximo de 4 bolhas por turno" in formato
    assert "<formato_das_bolhas>" in midia
    # 3 bolhas de texto (reconhecimento + valor + linha do book) e a 4ª só com intenção na mesa.
    assert "são 3 bolhas" in midia
    assert "mídia não é bolha" in midia
    assert "a 4ª é o empurrão de fechamento" in midia


def test_a_armadilha_de_voz_do_preco_seco_existe_e_esta_no_formato_dos_vizinhos() -> None:
    armadilhas = _bloco("armadilhas_de_voz")

    pares = re.findall(
        r"<par><errado>(.*?)</errado><certo>(.*?)</certo><porque>(.*?)</porque></par>", armadilhas
    )
    novos = [p for p in pares if "manda mais fotos" in p[0]]
    assert len(novos) == 1, "o par do pedido de foto sumiu ou está fora do formato <par>…</par>"
    errado, certo, porque = novos[0]

    # O lado errado é exatamente a fala que o Fernando reportou: preço seco + empurrão.
    assert "1h no meu local" in errado and "Seria que horas ?" in errado
    # O lado certo abre reconhecendo, cota e fecha no book.
    assert certo.index("Te mando sim amor") < certo.index("1h no meu local") < certo.index("book")
    # Voz: bolha curta, sem ponto final, número seco sem emoji.
    bolhas = [b.strip() for b in certo.split(" / ")]
    assert not any(b.endswith(".") for b in bolhas)
    assert not any(c in certo for c in ("🥰", "😊"))
    # E o par aponta pro dono da regra em vez de represcrevê-la.
    assert "<midia>" in porque
