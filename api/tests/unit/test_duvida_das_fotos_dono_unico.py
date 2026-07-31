"""A dúvida sobre as fotos tem um dono só (issue 13 do refactor do prompt).

`"é você mesma nas fotos?"` aparecia LITERALMENTE em dois blocos do BP_GERAL com prescrições
incompatíveis: o `<midia>` mandava o book (2-3 fotos + vídeo), o `<protocolo_disclosure>` mandava
uma resposta verbal de uma linha. O desvio que deveria desempatar ("quando a dúvida é sobre as
FOTOS, quem responde é o book do `<midia>`, não este bloco") mora no CABEÇALHO do
`<protocolo_disclosure>` — e o parágrafo que reivindicava a string está DENTRO desse mesmo bloco,
então o desvio se autoexcluía.

Depois do ticket: uma prescrição só (o book, no `<midia>`) e o outro site REFERENCIA. As duas
regras vizinhas que não podiam cair junto: teste de bot não ganha prova espontânea (queimar o book
num teste deixa ela sem mídia no fechamento) e detalhe físico fora dos blocos não vira número
inventado.

Sem DB e sem crédito: lê o prefixo geral pelo caminho real (`render_prefixo_geral`, nunca montando
a string fora — `agente/persona.py`).
"""

import re

from barra.agente.persona import render_prefixo_geral

_DUVIDA_DAS_FOTOS = ("é você mesma nas fotos?", "essas fotos são suas?")


def _bloco(nome: str) -> str:
    """O corpo de um bloco da conduta. Ancorado em INÍCIO DE LINHA: os dois blocos se citam por
    nome no meio do texto (`(<protocolo_disclosure>)`, `do <midia>`) e um casamento solto começaria
    na citação, engolindo o bloco vizinho inteiro."""
    texto = render_prefixo_geral()
    achado = re.search(rf"^<{nome}>$(.*?)^</{nome}>$", texto, re.S | re.M)
    assert achado is not None, f"bloco <{nome}> sumiu do BP_GERAL"
    return achado.group(1)


def test_a_pergunta_das_fotos_e_prescrita_so_no_midia() -> None:
    midia, disclosure = _bloco("midia"), _bloco("protocolo_disclosure")

    for literal in _DUVIDA_DAS_FOTOS:
        assert literal in midia, f"o site canônico perdeu o gatilho {literal!r}"
        assert literal not in disclosure, (
            f"{literal!r} voltou a ser reivindicada pelo <protocolo_disclosure> — é a colisão "
            "que o ticket 13 fechou (uma prescrição, o outro site referencia)"
        )
    # E o dono é dono de verdade: o gatilho continua mandando o BOOK, não uma foto tímida.
    assert "o book vai de uma vez" in midia


def test_o_protocolo_disclosure_referencia_o_midia_em_vez_de_prescrever() -> None:
    disclosure = _bloco("protocolo_disclosure")

    # Dois ponteiros: o do cabeçalho (onde "É você mesma?" é listada como gatilho do bloco) e o do
    # parágrafo do detalhe do anúncio, que é onde a fala "bem gata como nas fotos" atrai a pergunta.
    assert disclosure.count("<midia>") >= 2
    assert "quem responde é o book do <midia>" in disclosure


def test_teste_de_bot_continua_sem_book_e_sem_prova_espontanea() -> None:
    midia, disclosure = _bloco("midia"), _bloco("protocolo_disclosure")

    # <midia>: o carve-out que separa a dúvida da APARÊNCIA (book) do teste de humanidade (nunca).
    assert 'nunca como resposta a "é bot?"' in midia
    assert "Queimar o book num teste de bot" in midia
    # <protocolo_disclosure>: a negação em personagem, sem prova espontânea.
    assert "Negue em personagem" in disclosure
    assert "nunca prova espontânea" in disclosure


def test_detalhe_fisico_fora_dos_blocos_continua_sem_numero() -> None:
    disclosure = _bloco("protocolo_disclosure")

    assert "(altura, manequim)" in disclosure
    assert "não invente nem confirme número" in disclosure
    assert "Sou eu mesma amor, bem gata como nas fotos rs" in disclosure
