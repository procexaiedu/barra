"""O Vale dito no grupo (spec 0006, ticket 15; ADR-0045 §8, ADR-0047 §5) — sem banco.

Vale é o adiantamento que a casa dá à modelo no meio da temporada (*"tem que pagar uma conta de
500 reais, eu adianto"*) e que volta descontado no fechamento. O painel (ticket 05) é a porta
canônica; esta é a conveniente, e existe porque a frase é dita no grupo o tempo todo.

O que este arquivo pina — e nenhuma linha dele precisa de banco:

1. **A leitura**: a fala vira lançamento com o valor certo, nas grafias que o grupo usa.
2. **A fronteira com a Cobrança da agência, nos DOIS sentidos.** Os dois debitam a modelo e a
   confusão passaria despercebida no saldo — mas só a cobrança espera comprovante. As allowlists
   são disjuntas, e é isso que se afirma aqui.
3. **"Ficou com ela" NÃO é vale** (ADR-0047 §5): é a venda com bolso `dela` mais a ausência da
   transferência. Ler as duas coisas contaria o mesmo dinheiro duas vezes.
4. **Confiança baixa não lança**: adiantamento sem valor, ou com dois valores na mesma frase, vira
   a pergunta mínima que o módulo já tem — e a própria pergunta é reconhecível no log, que é o
   que faz o "500" seguinte ter dono em vez de virar receita de um anúncio incompleto.
5. **O efeito no razão**: o vale é débito dela, e o saldo com sinal muda pelo valor exato.

O que só o banco prova — o dedup por chave de conteúdo, a correção por quote no recibo, a anulação
pela deleção da fala e a origem `grupo` gravada na coluna — vive em
`tests/integracao/test_grupo_financeiro_vale_na_porta.py`, com `needs_db`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from barra.dominio.grupo_financeiro.cobranca import ler_cobranca
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA
from barra.dominio.grupo_financeiro.razao import (
    ValeNoRazao,
    VendaNoRazao,
    apurar,
)
from barra.dominio.grupo_financeiro.vale import (
    DESCRICAO_PADRAO,
    ValeHesitante,
    ValeLido,
    chave_de_conteudo_do_vale,
    e_pergunta_do_vale,
    ler_vale,
    montar_aviso_de_vale_duplicado,
    montar_pergunta_do_vale,
    montar_recibo_do_vale,
)

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
HOJE = date(2026, 8, 20)

COBRANCA_REAL = (
    "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80\nEnvia para o site e envia o comprovante"
)
"""A mensagem literal do export de 13/08 — a Cobrança da agência que o ticket 08 já registra."""


# --- a leitura ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("adiantei 500 pra ela", "500.00"),
        ("Adiantei R$ 500 pra ela", "500.00"),
        ("mandei um vale de 300", "300.00"),
        ("Adiantamento de R$ 1.200,00 pra Yasmin", "1200.00"),
        ("emprestei 400 pra ela ontem", "400.00"),
        ("tem que pagar uma conta de 500 reais, eu adianto", "500.00"),
        ("vale de 300,50 pra ela", "300.50"),
    ],
)
def test_a_fala_do_gestor_vira_vale_com_o_valor_certo(texto: str, esperado: str) -> None:
    lida = ler_vale(texto)
    assert isinstance(lida, ValeLido)
    assert lida.valor == Decimal(esperado)


def test_a_descricao_guarda_a_fala_do_gestor() -> None:
    """É ela que explica, no extrato do painel, de onde veio um débito que nasceu no WhatsApp."""
    lida = ler_vale("adiantei 500 pra ela pagar a conta de luz")
    assert isinstance(lida, ValeLido)
    assert lida.descricao == "adiantei 500 pra ela pagar a conta de luz"


def test_o_numero_que_nao_e_dinheiro_nao_e_vale() -> None:
    """ "2 horas" e "19h" moram na mesma frase que o adiantamento e nenhum dos dois é valor."""
    assert ler_vale("adiantei 2 horas o horário dela") is None


@pytest.mark.parametrize(
    "texto",
    [
        "vale a pena esperar esse cliente?",
        "não vale nada",
        "quanto vale 1h dela?",
        "600",
        "Foi pix ou din ?",
        "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca \n700 1h",
    ],
)
def test_o_que_o_grupo_diz_o_dia_inteiro_nao_e_vale(texto: str) -> None:
    """A palavra "vale" em função de VERBO é conversa. Só o substantivo abre a leitura."""
    assert ler_vale(texto) is None


def test_negacao_nao_lanca_debito() -> None:
    assert ler_vale("não vou adiantar mais nada pra ela") is None


def test_deslocamento_nao_e_vale() -> None:
    """O Uber tem lançamento próprio (ticket 12, ADR-0046): é reembolso de custo, não empréstimo."""
    assert ler_vale("adiantei 100 do uber dela") is None


# --- a fronteira com a Cobrança da agência, nos dois sentidos ------------------------------------


def test_a_cobranca_da_agencia_nao_e_lida_como_vale() -> None:
    """Sentido 1: serviço vendido a ela (anúncio, site) continua sendo cobrança."""
    assert ler_vale(COBRANCA_REAL) is None


def test_o_vale_nao_e_lido_como_cobranca_da_agencia() -> None:
    """Sentido 2: dinheiro emprestado não entra na fila que espera comprovante.

    As duas allowlists são disjuntas de propósito — a da cobrança é de rubricas de serviço, a do
    vale é de verbos de empréstimo. Ler um como o outro deixaria uma dívida cobrada para sempre.
    """
    assert ler_cobranca("adiantei 500 pra ela") is None
    assert ler_cobranca("mandei um vale de R$ 300 pra ela") is None


# --- "ficou com ela" não é vale (ADR-0047 §5) ----------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "esse valor da Ingrid de 1.200, 2 horas, ela ficou pra ela — contabiliza como um vale",
        "os 600 do Gabriel ficaram com ela",
        "ficou com você esse dinheiro",
    ],
)
def test_o_dinheiro_da_venda_que_ficou_com_ela_nao_vira_vale(texto: str) -> None:
    """É a venda com bolso `dela` mais a ausência da transferência — o razão já acerta sozinho.

    Lançar TAMBÉM um vale contaria o mesmo dinheiro duas vezes, e a dívida inventada sairia no
    fechamento no nome dela.
    """
    assert ler_vale(texto) is None


# --- confiança baixa não lança -------------------------------------------------------------------


def test_adiantamento_sem_valor_vira_pergunta_e_nao_lancamento() -> None:
    lida = ler_vale("adiantei pra ela")
    assert isinstance(lida, ValeHesitante)
    assert lida.motivo == "sem_valor"
    assert montar_pergunta_do_vale(lida) == f"{PREFIXO_DA_PERGUNTA}quanto foi o adiantamento?"


def test_dois_valores_na_mesma_frase_viram_pergunta_que_os_nomeia() -> None:
    """Perguntar "de qual?" sem repetir os números devolve ao grupo a pergunta que ele respondeu."""
    lida = ler_vale("adiantei 500, na verdade 300")
    assert isinstance(lida, ValeHesitante)
    assert lida.motivo == "valor_ambiguo"
    assert lida.valores == (Decimal("500.00"), Decimal("300.00"))
    assert montar_pergunta_do_vale(lida) == (
        f"{PREFIXO_DA_PERGUNTA}o adiantamento foi de R$ 500,00 ou R$ 300,00?"
    )


def test_o_mesmo_valor_repetido_e_enfase_e_nao_ambiguidade() -> None:
    lida = ler_vale("adiantei os 500 pra ela, os 500 mesmo")
    assert isinstance(lida, ValeLido)
    assert lida.valor == Decimal("500.00")


def test_a_hesitacao_guarda_a_fala_para_quando_a_resposta_chegar() -> None:
    """Sem isso o vale nascido de "adiantei pra ela" + "500" seria uma linha anônima no painel."""
    lida = ler_vale("adiantei pra ela")
    assert isinstance(lida, ValeHesitante)
    assert lida.descricao == "adiantei pra ela"
    assert DESCRICAO_PADRAO == "Vale adiantado"


def test_o_agente_reconhece_a_propria_pergunta_do_vale_no_log() -> None:
    """É o que faz o "500" seguinte ter dono — senão ele completa um anúncio e vira RECEITA."""
    sem_valor = ler_vale("adiantei pra ela")
    ambiguo = ler_vale("adiantei 500, na verdade 300")
    assert isinstance(sem_valor, ValeHesitante)
    assert isinstance(ambiguo, ValeHesitante)
    assert e_pergunta_do_vale(montar_pergunta_do_vale(sem_valor))
    assert e_pergunta_do_vale(montar_pergunta_do_vale(ambiguo))


def test_a_pergunta_do_anuncio_nao_e_confundida_com_a_do_vale() -> None:
    assert not e_pergunta_do_vale(f"{PREFIXO_DA_PERGUNTA}quanto foi esse atendimento?")
    assert not e_pergunta_do_vale("adiantei 500 pra ela")


# --- as falas do agente ---------------------------------------------------------------------------


def test_o_recibo_do_vale_e_curto_e_convida_a_correcao() -> None:
    recibo = montar_recibo_do_vale(valor=Decimal("500.00"), data=HOJE)
    assert recibo == (
        "💸 Registrei o vale: R$ 500,00 · 20/08 — desconto no fechamento. "
        "corrige aí se algo estiver errado"
    )


def test_o_recibo_do_vale_nao_usa_o_emoji_da_cobranca() -> None:
    """Quem confere de relance precisa ver que este débito NÃO espera comprovante."""
    recibo = montar_recibo_do_vale(valor=Decimal("500.00"), data=HOJE)
    assert not recibo.startswith("🧾")
    assert "cobrança" not in recibo.lower()


def test_o_aviso_de_duplicata_diz_qual_vale_venceu_o_dedup() -> None:
    aviso = montar_aviso_de_vale_duplicado(valor=Decimal("500.00"), data=HOJE)
    assert aviso == "♻️ Esse vale já estava registrado: R$ 500,00 · 20/08 — não lancei de novo."


# --- a chave de conteúdo -------------------------------------------------------------------------


def test_o_repost_da_mesma_fala_produz_a_mesma_chave() -> None:
    chave = chave_de_conteudo_do_vale(
        data=HOJE, valor=Decimal("500.00"), modelo_id=YASMIN, descricao="Adiantei 500 pra ela"
    )
    repost = chave_de_conteudo_do_vale(
        data=HOJE, valor=Decimal("500.00"), modelo_id=YASMIN, descricao="adiantei  500  PRA ELA"
    )
    assert chave == repost
    assert chave.startswith("vale|2026-08-20|500.00|")


def test_a_chave_muda_com_o_valor() -> None:
    a = chave_de_conteudo_do_vale(
        data=HOJE, valor=Decimal("500.00"), modelo_id=YASMIN, descricao="adiantei 500 pra ela"
    )
    b = chave_de_conteudo_do_vale(
        data=HOJE, valor=Decimal("600.00"), modelo_id=YASMIN, descricao="adiantei 600 pra ela"
    )
    assert a != b


# --- o efeito no razão ---------------------------------------------------------------------------


def test_o_vale_debita_a_modelo_e_muda_o_saldo_pelo_valor_exato() -> None:
    """Venda de R$ 1.200 no bolso dela com 50%: saldo -600. Um vale de 500 leva a -1.100."""
    venda = VendaNoRazao(
        valor=Decimal("1200.00"), bolso="dela", percentual_repasse_snapshot=Decimal("50")
    )
    sem_vale = apurar([venda])
    com_vale = apurar([venda, ValeNoRazao(valor=Decimal("500.00"))])

    assert sem_vale.saldo == Decimal("-600.00")
    assert com_vale.saldo == Decimal("-1100.00")
    assert com_vale.ela_deve
    assert com_vale.saldo == sem_vale.saldo - Decimal("500.00")


def test_o_vale_nunca_entra_na_base_de_comissao() -> None:
    """Adiantamento não é serviço prestado: ele debita e não credita nada."""
    razao = apurar([ValeNoRazao(valor=Decimal("500.00"))])
    assert razao.creditos == Decimal("0.00")
    assert razao.debitos == Decimal("500.00")
    assert [linha.tipo for linha in razao.linhas] == ["vale"]
