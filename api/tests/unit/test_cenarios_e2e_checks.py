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
    _cotou_completo_sozinho,
    _cotou_dobro_do_pacote,
    _ofereceu_local_proprio,
    _ofereceu_video_chamada,
    _propos_dentro_da_janela,
    _recusou_menage_sem_cotar,
    _repetiu_bolha_identica,
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
