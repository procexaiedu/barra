"""Preço do extra de um fetiche pago — cadastro (fonte de verdade) e o derivado da linha de 1h.

Unit puro (sem DB). Duas camadas:
- `extra_de_fetiche` — SITE ÚNICO da conta: com preço cadastrado no painel, o extra é esse
  número, fixo em qualquer pacote (revisão 11/08/2026 do ADR-0030); sem ele, cai no derivado.
- `calcular_preco_extra_fetiche` — o derivado do **ADR-0038**: o extra é o preço da linha de 1
  HORA do MESMO programa, no patamar de desconto vigente. Substitui o preço-hora do pacote
  (`preco_tabela / horas`, ADR-0030), que coincidia por acidente na parte linear da tabela
  (400/1h e 800/2h dão os mesmos 400) e divergia justamente onde o preço deixa de ser linear.

A tabela canônica dos casos é a da Catarina (programa Normal), ditada pelo dono do produto em
11/08/2026 — 1h a 400 (mínimo 300), 2h a 800 (mínimo 600), 3h a 1.000 (mínimo 900), pernoite a
2.000, 30min a 250.

**ADR-0039**: composição (casal/ménage, `cobra_por_pessoa`) deixou de ter regime próprio. Não há
mais uma conta "dobra o pacote" a testar aqui — a 2ª pessoa é o MESMO extra dos atos, e por isso
`extra_de_fetiche`/`calcular_preco_extra_fetiche` nem recebem mais `cobra_por_pessoa` nem
`preco_pacote` (o único consumidor do preço do pacote era o dobro).
"""

from decimal import Decimal

import pytest

from barra.dominio.atendimentos.service import (
    aceita_fetiche_pago,
    calcular_preco_extra_fetiche,
    extra_de_fetiche,
    preco_cadastrado_de_fetiche,
    valor_no_patamar,
)

# Linha de 1h da Catarina no Normal: (preço de tabela, piso absoluto da linha).
UMA_HORA = (Decimal("400"), Decimal("300"))

# (preço do pacote, horas) das outras durações da mesma tabela.
PACOTES = {
    "1h": (Decimal("400"), Decimal("1")),
    "2h": (Decimal("800"), Decimal("2")),
    "3h": (Decimal("1000"), Decimal("3")),
    "pernoite": (Decimal("2000"), Decimal("12")),
}


def _extra(pacote: str, patamar: str = "cheio") -> Decimal | None:
    _, horas = PACOTES[pacote]
    return calcular_preco_extra_fetiche(
        UMA_HORA,
        horas,
        patamar=patamar,  # type: ignore[arg-type]
    )


# --- o extra é a 1h, em qualquer duração (ADR-0038) -----------------------------------------


@pytest.mark.parametrize("pacote", list(PACOTES))
def test_extra_e_o_preco_da_uma_hora_em_qualquer_duracao(pacote: str) -> None:
    assert _extra(pacote) == Decimal("400")


def test_a_formula_antiga_coincidia_em_1h_e_2h_e_divergia_de_3h_em_diante() -> None:
    # É por isso que o preço-hora passou um ano parecendo certo: na parte LINEAR da tabela ele
    # dá o mesmo número. O ADR-0038 se paga na 3h e no pernoite, onde o preço-hora cobraria
    # +333 pelo MESMO ato que a 1h cobra 400.
    for pacote in ("1h", "2h"):
        preco, horas = PACOTES[pacote]
        assert _extra(pacote) == preco / horas
    for pacote in ("3h", "pernoite"):
        preco, horas = PACOTES[pacote]
        assert _extra(pacote) != preco / horas
        assert preco / horas < Decimal("400")


def test_totais_da_tabela_do_dono_do_produto() -> None:
    # Os números canônicos da decisão de 11/08/2026, no patamar cheio.
    assert PACOTES["1h"][0] + _extra("1h") == Decimal("800")
    assert PACOTES["1h"][0] + 2 * _extra("1h") == Decimal("1200")
    assert PACOTES["2h"][0] + _extra("2h") == Decimal("1200")
    assert PACOTES["3h"][0] + _extra("3h") == Decimal("1400")
    assert PACOTES["pernoite"][0] + _extra("pernoite") == Decimal("2400")


# --- patamar é estágio da escada, não percentual do pacote ----------------------------------


def test_extra_acompanha_o_patamar_da_escada() -> None:
    # 400 cheio -> 350 no degrau (12,5%) -> 300 no piso (25%, clampado pelo mínimo de 300).
    assert _extra("1h", "cheio") == Decimal("400")
    assert _extra("1h", "degrau") == Decimal("350")
    assert _extra("1h", "piso") == Decimal("300")


def test_no_piso_o_total_da_1h_e_600() -> None:
    piso_do_pacote = valor_no_patamar(*UMA_HORA, "piso")
    assert piso_do_pacote + _extra("1h", "piso") == Decimal("600")


def test_patamar_nao_e_o_fator_do_pacote_na_3h() -> None:
    # A armadilha explícita da decisão: a 3h tem piso ABSOLUTO de 900 sobre 1.000 (fator 0,9).
    # Aplicar esse fator ao extra daria 360 — número que não é preço de nada. O extra é o valor
    # da 1h NAQUELE estágio: 300. Total 900 + 300 = 1.200.
    piso_da_3h = valor_no_patamar(Decimal("1000"), Decimal("900"), "piso")
    assert piso_da_3h == Decimal("900")
    assert _extra("3h", "piso") == Decimal("300")
    assert piso_da_3h + _extra("3h", "piso") == Decimal("1200")


# --- fail-closed: sem linha de 1h não há extra derivado -------------------------------------


def test_sem_linha_de_uma_hora_nao_ha_extra() -> None:
    # O extra É a uma hora: programa cadastrado só na 2h não tem de onde derivar. None, nunca um
    # palpite (era exatamente o que o preço-hora fazia: inventava uma base a partir do pacote).
    assert calcular_preco_extra_fetiche(None, Decimal("2")) is None
    assert extra_de_fetiche(None, Decimal("2")) is None


def test_pacote_curto_nao_tem_fetiche_pago() -> None:
    # Decisão de 11/08/2026 (a linha de 30min da Catarina). Vale com e sem preço cadastrado.
    assert not aceita_fetiche_pago(Decimal("0.5"))
    assert extra_de_fetiche(UMA_HORA, Decimal("0.5")) is None
    assert extra_de_fetiche(UMA_HORA, Decimal("0.5"), preco_cadastrado=Decimal("350")) is None


def test_duracao_ausente_e_fail_closed() -> None:
    assert extra_de_fetiche(UMA_HORA, None) is None


# --- composição (casal/menage): MESMO extra dos atos, o pacote não dobra (ADR-0039) ----------
# A conta some da assinatura: `cobra_por_pessoa` e `preco_pacote` deixaram de ser parâmetros, e é
# isso que garante que não sobrou um segundo regime escondido. O que fica testável é o RESULTADO
# — a tabela que o dono do produto aprovou em 11/08/2026 para o total com a 2ª pessoa.


def test_a_composicao_nao_tem_mais_parametro_proprio_na_conta() -> None:
    # Gate estrutural: enquanto `cobra_por_pessoa`/`preco_pacote` existirem, existe um caminho
    # para o pacote dobrar de novo. O tipo é o que obriga cada chamador a se declarar.
    from inspect import signature

    for fn in (extra_de_fetiche, calcular_preco_extra_fetiche):
        params = set(signature(fn).parameters)
        assert "cobra_por_pessoa" not in params
        assert "preco_pacote" not in params


def test_totais_da_composicao_nos_tres_patamares() -> None:
    """Os números aprovados pelo dono em 11/08/2026 para "vocês dois", sobre a tabela da Catarina.

    A 1h NÃO muda (800 no cheio, o mesmo que o regime antigo dava) — a mudança começa a valer da
    2h em diante, onde o dobro dava 1.600 e agora dá 1.200.
    """
    esperado = {
        "1h": (Decimal("800"), Decimal("700"), Decimal("600")),
        "2h": (Decimal("1200"), Decimal("1050"), Decimal("900")),
        "3h": (Decimal("1400"), Decimal("1250"), Decimal("1200")),
        "pernoite": (Decimal("2400"), Decimal("2350"), Decimal("2300")),
    }
    minimos = {
        "1h": Decimal("300"),
        "2h": Decimal("600"),
        "3h": Decimal("900"),
        # Pernoite cadastrado COMO o mínimo: não é descontável, os três patamares colapsam.
        "pernoite": Decimal("2000"),
    }
    for pacote, (cheio, degrau, piso) in esperado.items():
        preco, _ = PACOTES[pacote]
        for patamar, total in (("cheio", cheio), ("degrau", degrau), ("piso", piso)):
            base = valor_no_patamar(preco, minimos[pacote], patamar)  # type: ignore[arg-type]
            assert base + _extra(pacote, patamar) == total


def test_o_dobro_do_pacote_deixou_de_ser_o_total_da_composicao() -> None:
    # O número que o ADR-0035 produzia (e que o output_guard legitimava) na 2h: 1.600. Sob o
    # ADR-0039 ele não sai de conta nenhuma.
    preco, _ = PACOTES["2h"]
    assert preco + _extra("2h") == Decimal("1200")
    assert preco + _extra("2h") != preco * 2


# --- preço cadastrado no painel = fonte de verdade (decisão 11/08/2026) ----------------------


def test_preco_cadastrado_vence_e_nao_varia_com_a_duracao_nem_com_o_patamar() -> None:
    # Inversão cadastrada a R$350: soma 350 em qualquer pacote. E não desce na escada — o
    # operador digitou um VALOR, não uma escada (quem desce é o pacote).
    for pacote in PACOTES:
        _, horas = PACOTES[pacote]
        for patamar in ("cheio", "degrau", "piso"):
            assert extra_de_fetiche(
                UMA_HORA,
                horas,
                patamar=patamar,  # type: ignore[arg-type]
                preco_cadastrado=Decimal("350"),
            ) == Decimal("350")


def test_sem_preco_cadastrado_cai_no_derivado() -> None:
    _, horas = PACOTES["pernoite"]
    assert extra_de_fetiche(UMA_HORA, horas, preco_cadastrado=None) == calcular_preco_extra_fetiche(
        UMA_HORA, horas
    )


def test_sentinel_de_flag_nao_e_preco_cadastrado() -> None:
    # `modelo_fetiches.preco` é reaproveitado como flag incluso/pago e o painel gravava
    # Decimal("1") quando pago=True (`_PRECO_PAGO_SENTINEL`) — quase todo o prod. Ler isso como
    # valor cotaria "+R$1"; tem que cair no derivado.
    assert preco_cadastrado_de_fetiche(Decimal("1")) is None
    assert preco_cadastrado_de_fetiche(None) is None
    assert preco_cadastrado_de_fetiche(350) == Decimal("350")
    _, horas = PACOTES["1h"]
    assert extra_de_fetiche(UMA_HORA, horas, preco_cadastrado=Decimal("1")) == Decimal("400")


def test_preco_cadastrado_de_composicao_e_o_TOTAL_do_extra() -> None:
    # ADR-0039: o `x 2` morreu. Uma coluna, uma regra — o número que o operador digita é o extra
    # inteiro, seja ele de um ato ou da 2ª pessoa. Era a segunda regra sobre a mesma coluna que
    # produzia o "cadastrei 700 e saiu 1400".
    _, horas = PACOTES["1h"]
    assert extra_de_fetiche(UMA_HORA, horas, preco_cadastrado=Decimal("700")) == Decimal("700")


# --- valor_no_patamar: despacho, não conta nova ----------------------------------------------


def test_valor_no_patamar_respeita_o_piso_absoluto_da_linha() -> None:
    # Linha cadastrada COMO o mínimo (30min a 250): os três patamares colapsam no mesmo número.
    assert valor_no_patamar(Decimal("250"), Decimal("250"), "cheio") == Decimal("250")
    assert valor_no_patamar(Decimal("250"), Decimal("250"), "degrau") == Decimal("250")
    assert valor_no_patamar(Decimal("250"), Decimal("250"), "piso") == Decimal("250")


def test_valor_no_patamar_sem_minimo_e_o_percentual_puro() -> None:
    assert valor_no_patamar(Decimal("400"), None, "degrau") == Decimal("350")
    assert valor_no_patamar(Decimal("400"), None, "piso") == Decimal("300")
