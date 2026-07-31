"""Checkers puros dos cenarios sinteticos e2e (evals/e2e/massa.py) — sem DB e sem credito.

Eles so sao exercidos na corrida REAL do runner (§0, gasta credito), entao um checker que sempre
devolve True passaria despercebido e tornaria o cenario decorativo. Estes testes fixam as duas
respostas de cada um sobre transcritos sinteticos.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from evals.e2e.massa import (
    _avancou_no_horario_apos_negociacao,
    _book_em_uma_bolha,
    _camisinha_direta_sem_incluso,
    _confirmou_a_hora_e_pediu_o_nome,
    _cotou_completo_sozinho,
    _cotou_dobro_do_pacote,
    _enquadrou_o_video,
    _mandou_o_book,
    _nao_precificou_a_insistencia,
    _ofereceu_a_hora_sem_dar_por_combinada,
    _ofereceu_local_proprio,
    _ofereceu_video_chamada,
    _propos_dentro_da_janela,
    _recusou_menage_sem_cotar,
    _recusou_o_ato_sem_levar_o_encontro,
    _repetiu_bolha_identica,
    _sem_book_no_turno,
    _sem_data_do_video,
    _sem_medida_inventada,
)


def _res(*textos: str) -> Any:
    return SimpleNamespace(turnos=[SimpleNamespace(texto=t) for t in textos])


def _dialogo(*pares: tuple[str, str]) -> Any:
    """Transcrito com a fala do cliente paralela a da IA (turnos_cliente[i] gerou turnos[i])."""
    return SimpleNamespace(
        turnos_cliente=[c for c, _ in pares],
        turnos=[SimpleNamespace(texto=ia) for _, ia in pares],
    )


def test_completo_sozinho_exige_um_preco_por_vez() -> None:
    # segunda venda certa: nomeia o Completo e traz so o valor DELE.
    assert _cotou_completo_sozinho(
        _res("400 1h no meu local", "Faço sim amor\n\nO completo é 600 1h")
    )
    # vitrine: os dois precos lado a lado — e o Completo sem numero nenhum tambem nao cota.
    assert not _cotou_completo_sozinho(_res("Tenho dois programas: 400 e o completo 600"))
    assert not _cotou_completo_sozinho(_res("Faço completo sim amor"))


def test_bolha_repetida_pega_a_re_cotacao_copiada() -> None:
    # a repergunta de preco respondida com OUTRAS palavras passa.
    assert not _repetiu_bolha_identica(_res("400 1h no meu local", "É 400 a 1h amor"))
    # a mesma bolha reenviada literalmente (robo travado) nao passa — nem com espacos/caixa diferentes.
    assert _repetiu_bolha_identica(_res("400 1h no meu local", "400 1h  No Meu Local"))
    # cortesia curta repete a vontade: bolha de menos de 3 palavras nao conta.
    assert not _repetiu_bolha_identica(_res("Oii\n\namor", "Oii\n\namor"))


def test_avanco_pos_negociacao_exige_hora_sem_recusa_nem_re_cotacao() -> None:
    escada = ("e por 280?", "Poxa amor não consigo")
    # a pergunta de horario DEPOIS da escada e o sim: ela crava a hora e nao volta ao preco.
    assert _avancou_no_horario_apos_negociacao(
        _dialogo(escada, ("que horas você pode hoje ?", "Perfeito\n\nConsigo às 22h amor ?"))
    )
    # repetir a recusa e o erro que o <desconto> nomeia.
    assert not _avancou_no_horario_apos_negociacao(
        _dialogo(escada, ("que horas você pode hoje ?", "Não consigo menos amor\n\nMas tenho 22h"))
    )
    # re-cotar tambem: o valor da mesa ja esta aceito, o numero nao volta.
    assert not _avancou_no_horario_apos_negociacao(
        _dialogo(escada, ("que horas você pode hoje ?", "São 300 amor\n\nConsigo às 22h ?"))
    )
    # responder sem hora nenhuma deixa a venda esperando um sim que ja veio.
    assert not _avancou_no_horario_apos_negociacao(
        _dialogo(escada, ("que horas você pode hoje ?", "Me fala o que prefere amor"))
    )


def test_janela_vaga_exige_proposta_dentro_da_janela_dele() -> None:
    pergunta = ("oi quanto é 1 hora?", "400 1h no meu local amor")
    # o piso e as 14h, ele disse "de noite": a proposta cai na janela DELE.
    assert _propos_dentro_da_janela(
        _dialogo(pergunta, ("pode ser de noite", "Consigo às 21h, fecha ?")), "de noite"
    )
    # o bug: propor o piso, um horario que ele acabou de excluir.
    assert not _propos_dentro_da_janela(
        _dialogo(pergunta, ("pode ser de noite", "Consigo às 14h amor ?")), "de noite"
    )
    # misturar as duas nao salva: a diurna continua sendo hora que ele excluiu.
    assert not _propos_dentro_da_janela(
        _dialogo(pergunta, ("pode ser de noite", "Tenho 14h ou 21h amor")), "de noite"
    )
    # responder sem hora nenhuma deixa a janela dele sem proposta.
    assert not _propos_dentro_da_janela(
        _dialogo(pergunta, ("pode ser de noite", "Perfeito amor, me confirma")), "de noite"
    )
    # a DURACAO ("1h") nao e proposta de horario: nao conta de nenhum dos dois lados.
    assert not _propos_dentro_da_janela(
        _dialogo(pergunta, ("pode ser de noite", "A 1h fica 400 amor")), "de noite"
    )
    # janela sem faixa mapeada e erro de cenario, nao um check que passa em silencio.
    with pytest.raises(ValueError):
        _propos_dentro_da_janela(_dialogo(("oi", "Oii")), "quando der")


def test_local_proprio_pega_a_oferta_de_quem_so_se_desloca() -> None:
    # o formato certo de quem so se desloca: ela indo, com o uber.
    assert not _ofereceu_local_proprio(_res("400 1h + o uber ida e volta amor"))
    # oferecer um local que ela nao tem, em qualquer das paráfrases.
    assert _ofereceu_local_proprio(_res("400 1h no meu local"))
    assert _ofereceu_local_proprio(_res("Vem aqui amor rs"))
    assert _ofereceu_local_proprio(_res("Te espero aqui, é bem tranquilo"))


# --- Issue 23: menage (ADR-0035) e vídeo chamada fora da tabela (ADR-0021) -------------------

_PEDIU_A_DOIS = "e se eu levar minha namorada junto, nós dois com você? quanto fica as 2h?"


def test_dobro_do_pacote_reprova_o_preco_hora_dos_atos() -> None:
    cotou = ("oi, quanto é 2 horas?", "700 as 2h no meu local amor")
    # o certo: 2 pessoas = o pacote DOBRADO (700x2), na resposta ao pedido dele.
    assert _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Faço sim amor\n\nPra vocês dois fica 1400 as 2h")), 700, 2
    )
    # "1.400" com separador de milhar e o mesmo numero.
    assert _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Pra vocês dois fica 1.400 amor")), 700, 2
    )
    # o erro que o ADR-0035 nomeia: cotar pelo regime-ato (pacote + preco-hora = 700+350).
    assert not _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Fica 1050 amor, 700 + 350 da sua namorada")), 700, 2
    )
    # o "+Extra" sozinho tambem e o regime errado.
    assert not _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "É +350 pela sua namorada amor")), 700, 2
    )
    # trazer o dobro E o numero do ato na mesma bolha nao salva: ele viu os dois precos.
    assert not _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Fica 1400, ou 1050 se for so uma hora dela")), 700, 2
    )
    # responder sem valor nenhum deixa o pedido dele sem cotacao.
    assert not _cotou_dobro_do_pacote(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Faço sim amor, adoro rs")), 700, 2
    )
    # 1h faria dobro e preco-hora coincidirem: e erro de cenario, nao um check que passa em silencio.
    with pytest.raises(ValueError):
        _cotou_dobro_do_pacote(_dialogo((_PEDIU_A_DOIS, "1400 amor")), 400, 1)


def test_menage_fora_do_cardapio_exige_recusa_sem_dobrar_nem_prometer_amiga() -> None:
    cotou = ("oi, quanto é 2 horas?", "700 as 2h no meu local amor")
    # sem a secao "Por pessoa": recusa aberta, e a venda dela segue de pe.
    assert _recusou_menage_sem_cotar(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Não faço amor\n\nMas comigo seria que horas ?")),
        [400, 700],
    )
    # cotar o dobro e justamente o que ela nao tem pra vender.
    assert not _recusou_menage_sem_cotar(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Pra vocês dois fica 1400 amor")), [400, 700]
    )
    # aceitar sem recusar, mesmo sem numero, ja promete o que nao existe.
    assert not _recusou_menage_sem_cotar(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Faço sim amor rs")), [400, 700]
    )
    # recusar agora e dobrar dois turnos depois e o mesmo erro, so mais tarde.
    assert not _recusou_menage_sem_cotar(
        _dialogo(
            cotou,
            (_PEDIU_A_DOIS, "Não faço amor"),
            ("vai, faz um precinho pros dois", "Então pros dois fica 1400"),
        ),
        [400, 700],
    )
    # prometer amiga tambem esta fora: sem a secao, ela nao tem dupla pra oferecer.
    assert not _recusou_menage_sem_cotar(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Não faço amor\n\nDeixa eu ver com ela e te retorno")),
        [400, 700],
    )
    # a recusa de INDICAR outra (<fora_do_cardapio>) nao e promessa de amiga — continua passando.
    assert _recusou_menage_sem_cotar(
        _dialogo(cotou, (_PEDIU_A_DOIS, "Não faço amor\n\nNão indico não, só falo por mim rs")),
        [400, 700],
    )


# --- Issue 13: a dúvida sobre as FOTOS tem um dono só (o book do <midia>) --------------------


def _com_tools(*trios: tuple[str, str, list[str]]) -> Any:
    """Transcrito com as tools do turno: (fala do cliente, texto da IA, tools chamadas)."""
    return SimpleNamespace(
        turnos_cliente=[c for c, _, _ in trios],
        turnos=[SimpleNamespace(texto=ia, tool_calls=tools) for _, ia, tools in trios],
    )


_DUVIDA = "essas fotos são suas mesmo ?"
_TESTE_BOT = "isso aí é resposta automática né kkk"
_MEDIDA = "vc tem quantos de altura ? qual seu manequim ?"


def test_book_na_duvida_exige_mais_de_uma_midia_no_mesmo_turno() -> None:
    # o book: 2-3 fotos + o vídeo logo em seguida, tudo no turno da dúvida.
    assert _mandou_o_book(
        _com_tools((_DUVIDA, "Sou eu sim amor\n\nVocê vai gostar 🥰", ["enviar_midia"] * 3)),
        "essas fotos são suas",
    )
    # uma foto tímida não é o book ("não vá de conta-gotas").
    assert not _mandou_o_book(
        _com_tools((_DUVIDA, "Sou eu sim amor", ["enviar_midia"])), "essas fotos são suas"
    )
    # responder só em texto é a prescrição que o ticket tirou do <protocolo_disclosure>.
    assert not _mandou_o_book(
        _com_tools((_DUVIDA, "Sou eu mesma amor, bem gata como nas fotos rs", [])),
        "essas fotos são suas",
    )
    # o book três turnos depois não responde a dúvida — e o probe que nunca rodou não passa.
    assert not _mandou_o_book(
        _com_tools(("oi quanto é 1 hora?", "400 1h no meu local", ["enviar_midia"] * 2)),
        "essas fotos são suas",
    )


def test_teste_de_bot_reprova_a_prova_espontanea() -> None:
    # negação em personagem, sem mídia nenhuma.
    assert _sem_book_no_turno(
        _com_tools((_TESTE_BOT, "Que isso amor, sou eu rs", [])), "resposta automática"
    )
    # queimar o book num teste é justamente o que deixa ela sem mídia no fechamento.
    assert not _sem_book_no_turno(
        _com_tools((_TESTE_BOT, "Sou eu sim amor", ["enviar_midia", "enviar_midia"])),
        "resposta automática",
    )
    # probe que não rodou (a corrida terminou antes) não vira aprovação silenciosa.
    assert not _sem_book_no_turno(_com_tools(("oi", "Oii", [])), "resposta automática")


def test_detalhe_fisico_reprova_a_medida_cravada() -> None:
    ok = "Sou eu mesma amor, bem gata como nas fotos rs"
    assert _sem_medida_inventada(_com_tools((_MEDIDA, ok, [])), "manequim")
    # as formas de inventar: altura em metros, medida com unidade, manequim/peso com rótulo.
    for inventado in ("Tenho 1,70 amor", "1m70 amor rs", "175 cm amor", "60 kg amor"):
        assert not _sem_medida_inventada(_com_tools((_MEDIDA, inventado, [])), "manequim")
    assert not _sem_medida_inventada(_com_tools((_MEDIDA, "Visto 38 amor", [])), "manequim")
    assert not _sem_medida_inventada(_com_tools((_MEDIDA, "Manequim 40 rs", [])), "manequim")
    # preço, duração e horário do mesmo turno NÃO são medida — o check não pode reprová-los.
    assert _sem_medida_inventada(
        _com_tools((_MEDIDA, f"{ok}\n\n400 1h no meu local\n\nConsigo às 22h ?", [])), "manequim"
    )
    assert _sem_medida_inventada(_com_tools((_MEDIDA, "Fica 1.400 as 2h amor", [])), "manequim")


# --- Issue 14: uma bolha, legenda vazia e o enquadramento do vídeo ---------------------------


def _turno_do_book(fala: str, texto: str, *midias: dict[str, Any]) -> Any:
    """Um turno com N `enviar_midia` (args na ordem) + a `registrar_extracao` que todo turno real
    leva junto — o checker precisa filtrar pelo NOME da tool, não contar posições."""
    nomes = ["registrar_extracao", *["enviar_midia"] * len(midias)]
    args: list[dict[str, Any]] = [{"estado": "Qualificado"}, *midias]
    return SimpleNamespace(
        turnos_cliente=[fala],
        turnos=[SimpleNamespace(texto=texto, tool_calls=nomes, tool_args=args)],
    )


_FOTO: dict[str, Any] = {"tag": "corpo", "tipo": "foto"}
_VIDEO: dict[str, Any] = {"tag": "corpo", "tipo": "video"}
_UMA_LINHA = "Gravei um vídeo pra você 🥰"


def test_book_em_uma_bolha_exige_video_depois_da_foto_e_legenda_vazia() -> None:
    # o book certo: fotos, o vídeo em seguida, UMA bolha e nenhuma legenda.
    assert _book_em_uma_bolha(
        _turno_do_book(_DUVIDA, _UMA_LINHA, _FOTO, _FOTO, _VIDEO), "essas fotos são suas"
    )
    # `tipo` omitido é foto (default da tool) — não pode virar vídeo por acidente.
    assert not _book_em_uma_bolha(
        _turno_do_book(_DUVIDA, _UMA_LINHA, {"tag": "corpo"}, {"tag": "corpo"}),
        "essas fotos são suas",
    )
    # a legenda preenchida é a duplicação que a bolha única existe pra evitar.
    assert not _book_em_uma_bolha(
        _turno_do_book(_DUVIDA, _UMA_LINHA, _FOTO, {**_VIDEO, "legenda": "Gravei pra você rs"}),
        "essas fotos são suas",
    )
    # duas bolhas: o prompt autorizou UMA linha.
    assert not _book_em_uma_bolha(
        _turno_do_book(_DUVIDA, f"Sou eu sim amor\n\n{_UMA_LINHA}", _FOTO, _VIDEO),
        "essas fotos são suas",
    )
    # vídeo antes da foto inverte a ordem que o <midia> prescreve.
    assert not _book_em_uma_bolha(
        _turno_do_book(_DUVIDA, _UMA_LINHA, _VIDEO, _FOTO), "essas fotos são suas"
    )
    # probe que não rodou não vira aprovação silenciosa.
    assert not _book_em_uma_bolha(_turno_do_book("oi", "Oii"), "essas fotos são suas")


def test_enquadramento_do_video_mora_na_bolha_e_nao_entrega_o_acervo() -> None:
    def _bolha(texto: str) -> Any:
        return _turno_do_book(_DUVIDA, texto, _FOTO, _VIDEO)

    assert _enquadrou_o_video(_bolha(_UMA_LINHA), "essas fotos são suas")
    assert _enquadrou_o_video(_bolha("Gravei pensando em você rs"), "essas fotos são suas")
    assert _enquadrou_o_video(_bolha("Fiz esse só pra você amor"), "essas fotos são suas")
    # mídia crua: o vídeo sai sem o argumento que o justifica.
    assert not _enquadrou_o_video(_bolha("Olha só amor 🥰"), "essas fotos são suas")
    # e o enquadramento não sobrevive à revelação de que o vídeo é acervo.
    assert not _enquadrou_o_video(
        _bolha("Gravei pra você amor\n\nÉ um vídeo antigo mas você vai gostar"),
        "essas fotos são suas",
    )
    assert not _enquadrou_o_video(
        _bolha("Gravei pra você rs\n\nJá tinha gravado esse aqui"), "essas fotos são suas"
    )


def test_quando_gravou_nao_recebe_data() -> None:
    quando = "e esse vídeo você gravou quando ?"
    # a resposta prescrita: repete o enquadramento e volta pro encontro.
    assert _sem_data_do_video(
        _com_tools((quando, "Gravei pensando em você rs\n\nVem hoje amor ?", [])), "gravou quando"
    )
    assert _sem_data_do_video(_com_tools((quando, "Agora de manhã amor rs", [])), "gravou quando")
    # a data no passado é o que entrega o acervo.
    for datado in ("Gravei ontem amor", "Faz uns dias amor rs", "Foi semana passada rs"):
        assert not _sem_data_do_video(_com_tools((quando, datado, [])), "gravou quando")
    # a proposta de encontro do mesmo turno é FUTURA — não pode contaminar.
    assert _sem_data_do_video(
        _com_tools((quando, "Gravei pra você rs\n\nTe espero amanhã amor", [])), "gravou quando"
    )


def test_oferta_de_chamada_distingue_a_oferta_da_recusa() -> None:
    # a conduta de quem TEM a chamada na tabela — e o erro de quem nao tem.
    assert _ofereceu_video_chamada(_res("Podemos fazer uma vídeo chamada amor"))
    assert _ofereceu_video_chamada(_res("Faço chamada sim amor\n\nA de 30min fica 300"))
    assert _ofereceu_video_chamada(_res("Te ligo agora amor rs"))
    # a recusa certa CONTEM as mesmas palavras da oferta: sem o guarda de negacao, reprovaria ela.
    assert not _ofereceu_video_chamada(_res("Não faço chamada amor\n\nMas te mando uma foto rs"))
    assert not _ofereceu_video_chamada(_res("Chamada eu não faço amor"))
    # falar de chamada sem oferecer nada tambem nao e oferta.
    assert not _ofereceu_video_chamada(_res("Chamada de vídeo não entra no que eu faço"))
    # e a bolha que nem toca no assunto, menos ainda.
    assert not _ofereceu_video_chamada(_res("Te espero amor, é bem tranquilo aqui"))


# --- Issue 15: <fetiches> vazio — a recusa curta, a camisinha e a insistência com dinheiro -----

_PEDIU_ATO = "vc faz beijo grego ?"
_PERGUNTOU_SEM = "e sem camisinha, tá incluso ?"
_OFERECEU_DINHEIRO = "pago 2000 a mais pelo beijo grego então"


def test_recusa_do_ato_e_curta_sem_preco_e_nao_leva_o_encontro() -> None:
    # a conduta prescrita: recusa de mulher, só do item, e o encontro segue oferecido.
    assert _recusou_o_ato_sem_levar_o_encontro(
        _dialogo((_PEDIU_ATO, "Não faço amor\n\nMas te espero rs")), "beijo grego"
    )
    assert _recusou_o_ato_sem_levar_o_encontro(
        _dialogo((_PEDIU_ATO, "Não tenho costume rs")), "beijo grego"
    )
    # sem recusa nenhuma (ela topou) reprova.
    assert not _recusou_o_ato_sem_levar_o_encontro(
        _dialogo((_PEDIU_ATO, "Faço sim amor rs")), "beijo grego"
    )
    # cotar o ato é o erro do bloco vazio: "o que não está na lista não existe por dinheiro nenhum".
    assert not _recusou_o_ato_sem_levar_o_encontro(
        _dialogo((_PEDIU_ATO, "Não faço não amor, mas por 300 a mais eu penso rs")), "beijo grego"
    )
    # a recusa que cresce e derruba o encontro é o outro lado do critério.
    for larga in (
        "Não faço amor\n\nEntão melhor deixar pra outra vez",
        "Não faço isso amor, não vou te atender assim",
        "Não faço nada disso amor",
    ):
        assert not _recusou_o_ato_sem_levar_o_encontro(_dialogo((_PEDIU_ATO, larga)), "beijo grego")
    # probe que não rodou não vira aprovação silenciosa.
    assert not _recusou_o_ato_sem_levar_o_encontro(_dialogo(("oi", "Oii")), "beijo grego")


def test_camisinha_sai_direta_e_nunca_como_item_incluso() -> None:
    # a afirmação direta do <fora_do_cardapio> — em qualquer das formas dela.
    assert _camisinha_direta_sem_incluso(
        _dialogo((_PERGUNTOU_SEM, "Só faço com camisinha amor")), "sem camisinha"
    )
    assert _camisinha_direta_sem_incluso(
        _dialogo((_PERGUNTOU_SEM, "Não amor, sexo seguro com camisinha rs")), "sem camisinha"
    )
    # a recusa sem a afirmação deixa a porta aberta ("com camisinha" é o que fecha).
    assert not _camisinha_direta_sem_incluso(
        _dialogo((_PERGUNTOU_SEM, "Não faço amor")), "sem camisinha"
    )
    # e um incluso fantasma em QUALQUER turno reprova, mesmo com a afirmação certa depois — é a
    # falha medida em prod com o bloco vazio (issue 07).
    assert not _camisinha_direta_sem_incluso(
        _dialogo(
            ("oi quanto é 1 hora?", "Beijo na boca e oral sem camisinha tá incluso amor"),
            (_PERGUNTOU_SEM, "Só faço com camisinha amor"),
        ),
        "sem camisinha",
    )
    # o incluso legítimo do PROGRAMA (não sai do <fetiches>) não pode ser confundido com ele.
    assert _camisinha_direta_sem_incluso(
        _dialogo(
            ("faz completo?", "O completo tem anal incluso amor"),
            (_PERGUNTOU_SEM, "Só faço com camisinha amor"),
        ),
        "sem camisinha",
    )
    assert not _camisinha_direta_sem_incluso(_dialogo(("oi", "Oii")), "sem camisinha")


def test_insistencia_com_dinheiro_nao_recebe_numero() -> None:
    assert _nao_precificou_a_insistencia(
        _dialogo((_OFERECEU_DINHEIRO, "Poxa amor não faço mesmo")), "pago 2000"
    )
    # precificar o que ela não faz é exatamente o que a regra proíbe.
    assert not _nao_precificou_a_insistencia(
        _dialogo((_OFERECEU_DINHEIRO, "Por 2500 eu faço amor rs")), "pago 2000"
    )
    assert not _nao_precificou_a_insistencia(_dialogo(("oi", "Oii")), "pago 2000")


# Issue 17: os dois "sins". `_SIM_AO_VALOR` é a pergunta de horário que, depois da negociação de
# preço, equivale ao aceite (<desconto>); `_SIM_A_HORA` é o aceite da hora que ELA propôs — e é só
# esse segundo que licencia o verbo de confirmação.
_SIM_AO_VALOR = "que horas você pode hoje ?"
_SIM_A_HORA = "pode ser, fechou"


def test_o_sim_ao_valor_recebe_oferta_de_hora_com_interrogacao() -> None:
    # a conduta certa: propõe a hora, com "?", sem dar por combinada.
    assert _ofereceu_a_hora_sem_dar_por_combinada(
        _dialogo((_SIM_AO_VALOR, "Consigo às 22h, fecha ?")), "que horas você pode"
    )
    assert _ofereceu_a_hora_sem_dar_por_combinada(
        _dialogo((_SIM_AO_VALOR, "Perfeito\n\nPosso às 14h amor, fecha ?")), "que horas você pode"
    )
    # o bug do ticket: o verbo do <fechamento> num sim que ainda não é o da hora.
    for verbo in (
        "Posso confirmar às 22h ?",
        "Vamos confirmar 14h amor ?",
        "Fechamos 22h então ?",
        "Confirmado 22h amor",
    ):
        assert not _ofereceu_a_hora_sem_dar_por_combinada(
            _dialogo((_SIM_AO_VALOR, verbo)), "que horas você pode"
        )
    # sem a interrogação a proposta vira promessa de retorno ("te confirmo às 18h").
    assert not _ofereceu_a_hora_sem_dar_por_combinada(
        _dialogo((_SIM_AO_VALOR, "Consigo às 22h")), "que horas você pode"
    )
    # e responder sem hora nenhuma não é proposta.
    assert not _ofereceu_a_hora_sem_dar_por_combinada(
        _dialogo((_SIM_AO_VALOR, "Que bom amor rs")), "que horas você pode"
    )
    # probe que não rodou não vira aprovação silenciosa.
    assert not _ofereceu_a_hora_sem_dar_por_combinada(
        _dialogo(("oi", "Oii")), "que horas você pode"
    )


def test_o_sim_a_hora_recebe_confirmacao_e_o_nome() -> None:
    assert _confirmou_a_hora_e_pediu_o_nome(
        _dialogo((_SIM_A_HORA, "Confirmado\n\nQual seu nome amor?")), "pode ser, fechou"
    )
    assert _confirmou_a_hora_e_pediu_o_nome(
        _dialogo((_SIM_A_HORA, "Perfeito\n\nComo você se chama amor ?")), "pode ser, fechou"
    )
    # fechar sem pedir o nome deixa a metade da regra de fora...
    assert not _confirmou_a_hora_e_pediu_o_nome(
        _dialogo((_SIM_A_HORA, "Confirmado amor")), "pode ser, fechou"
    )
    # ...e reofertar a hora que ele acabou de aceitar é não ter fechado nada.
    assert not _confirmou_a_hora_e_pediu_o_nome(
        _dialogo((_SIM_A_HORA, "Então às 22h ?")), "pode ser, fechou"
    )
    assert not _confirmou_a_hora_e_pediu_o_nome(_dialogo(("oi", "Oii")), "pode ser, fechou")
