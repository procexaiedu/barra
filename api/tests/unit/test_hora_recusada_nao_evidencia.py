"""Hora que a IA RECUSOU não evidencia horário (loop-massa r3, eixo `retomada_pos_silencio` t6).

O cliente pediu 9h, a IA respondeu `"Poxa amor, 9h não consigo / Pode ser às 10h ?"` e o sistema
carimbou `horario_evidenciado`, promoveu `Qualificado→Aguardando_confirmacao`, reservou o slot às
09:00 e abriu o gate estrutural do número do endereço (ADR-0026) um turno cedo. O detector de
janela mede *"o cliente pronunciou uma hora"* — e só isso; nada verificava se a modelo topou.

O conserto mora no CONSUMIDOR, não na DESC do produtor: a DESC do `horario_desejado` manda anotar
a hora COMO ELA FOI DITA ("anota, não julga") e isso é desenho — o VALOR continua gravado. O que
cai é a MARCA, que é o que a tabela de pré-condições consulta para não reservar palpite. Também
não cabe no detector de janela: a recusa nasce na fala DELA, que só existe depois de ele rodar.

Unit puro (sem DB): o scanner de fala + o predicado do consumidor + o efeito no SQL da marca.
"""

from datetime import time
from typing import Any

from barra.dominio.atendimentos.service import (
    _hora_recusada_pela_ia,
    _marca_horario_evidenciado,
    horas_recusadas_na_fala,
)

# A fala real do t6 (trace 0b04b7bf), com as duas bolhas do turno agregadas como o
# `extrair_texto_do_turno` as entrega ao domínio.
_FALA_T6 = "Poxa amor, 9h não consigo\n\nPode ser às 10h ?"


def test_scanner_pega_a_hora_recusada_e_nao_a_ofertada() -> None:
    """O corte por CLÁUSULA é o que separa as duas: recusada e oferta moram na MESMA fala do
    turno, e uma janela de N caracteres fundiria as duas num único match."""
    assert horas_recusadas_na_fala(_FALA_T6) == {9}


def test_scanner_cobre_as_formas_de_recusa_do_corpus() -> None:
    for fala, esperado in (
        ("não consigo às 22h", {22}),
        ("22h não dá amor", {22}),
        ("impossível 21h", {21}),
        ("nao tenho como as 9h", {9}),
    ):
        assert horas_recusadas_na_fala(fala) == esperado, fala


def test_oferta_e_cotacao_nao_recusam_hora_nenhuma() -> None:
    for fala in ("Consigo às 20h, fecha ?", "Te espero às 22h amor", "400 a 1h no meu local"):
        assert horas_recusadas_na_fala(fala) == set(), fala


def test_recusa_de_desconto_com_duracao_nao_recusa_a_hora() -> None:
    """Mesmo veto de contexto de preço do lado do agente: com preço na cláusula, o "Nh" é DURAÇÃO
    vendida — "não consigo 250 na 1h" recusa o desconto, não um encontro à 01:00."""
    for fala in ("Poxa amor não consigo 250 na 1h", "não consigo fazer 300 em 1h"):
        assert horas_recusadas_na_fala(fala) == set(), fala


def test_predicado_do_consumidor_compara_a_hora_do_payload() -> None:
    assert _hora_recusada_pela_ia({"horario_desejado": "09:00:00"}, _FALA_T6) is True
    # A hora que ela OFERTOU no mesmo fôlego não é recusada.
    assert _hora_recusada_pela_ia({"horario_desejado": "10:00:00"}, _FALA_T6) is False
    # `time` (fallback de tempo imediato) e string ISO (payload da tool) valem igual.
    assert _hora_recusada_pela_ia({"horario_desejado": time(9, 0)}, _FALA_T6) is True
    # Sem hora no payload ou sem fala da IA no turno, não há o que conferir.
    assert _hora_recusada_pela_ia({}, _FALA_T6) is False
    assert _hora_recusada_pela_ia({"horario_desejado": "09:00:00"}, None) is False


def _sql_da_marca(evidenciado: bool) -> str:
    sets: list[str] = []
    valores: list[Any] = []
    _marca_horario_evidenciado(sets, valores, {"horario_desejado": "09:00:00"}, set(), evidenciado)
    return " ".join(sets)


def test_marca_nao_e_carimbada_quando_a_evidencia_cai() -> None:
    """O efeito no UPSERT: com a evidência negada pelo consumidor, a marca não vira `true` — cai
    no ramo do VALOR (o horário novo sem evidência é palpite), e é ele que o freio da r1 lê no hop
    `Qualificado→Aguardando_confirmacao`. O valor do horário segue gravado pelo `_montar_upsert`."""
    assert _sql_da_marca(True) == "horario_evidenciado = true"
    assert "horario_evidenciado = true" not in _sql_da_marca(False)
    assert "IS DISTINCT FROM" in _sql_da_marca(False)
