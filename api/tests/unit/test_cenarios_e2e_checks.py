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
    _ofereceu_local_proprio,
    _propos_dentro_da_janela,
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
