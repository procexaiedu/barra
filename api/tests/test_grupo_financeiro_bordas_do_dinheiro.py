"""As três bordas do dinheiro do grupo, sem banco (spec 0006; tickets 11, 12 e 13).

Três tickets irmãos que mexem nos mesmos arquivos porque são o mesmo assunto: **o que acontece
quando o dinheiro não entra pelo caminho simples** — não foi pix nem espécie, veio junto com um
Uber, ou foi parar na mão de outra modelo.

1. **Cartão virou três formas** (ADR-0046 §4). Débito, crédito e link são operações distintas e
   cada uma concilia no seu extrato; "cartão" como guarda-chuva deixou de existir. Nenhuma das
   três espera comprovante Pix — a prova é o print da maquininha, que este módulo não lê — e o
   bruto **não** é reduzido por taxa nenhuma (decisão do dono do produto, ADR-0045 §3).
2. **Deslocamento tem dois valores** (ADR-0046 §6). O antecipado que o cliente mandou (receita) e
   o que o Uber custou (custo). Com um número só, "mandou 100 e o Uber custou 60" seria
   indistinguível de "ninguém mandou nada e o Uber custou 15" — e o segundo caso é **crédito**
   dela. Este arquivo prova os quatro casos como UMA conta, não como uma tabela.
3. **Festinha: uma recebe por todas** (ADR-0045 §6). Continuam sendo N linhas, uma por modelo e
   cada uma no valor dela (ADR-0043) — o faturamento individual é o que não pode sumir. O que
   muda é de quem é o débito do bruto, e quem sai da cobrança de comprovante.

Tudo aqui é puro: leitor de fala, planejador e razão. O que só o banco prova (a coluna
`recebido_por_modelo_id` gravada, a linha em `deslocamentos_da_venda`, a fila de abate mudando de
dona) precisa das migrations da onda `20260820`, que ainda **não** estão aplicadas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from barra.dominio.grupo_financeiro.anuncio import AnuncioDeVenda
from barra.dominio.grupo_financeiro.deslocamento import PARTE_PADRAO, planejar_deslocamento
from barra.dominio.grupo_financeiro.ficha import (
    FichaDeAgendamento,
    ParticipanteDaFicha,
    bolso_da_promocao,
    planejar_promocao,
)
from barra.dominio.grupo_financeiro.modelos import FormaPagamento, VendaRegistrada
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes
from barra.dominio.grupo_financeiro.pagamento import ler_fala_de_pagamento
from barra.dominio.grupo_financeiro.pendencia import (
    em_especie,
    espera_comprovante,
    espera_comprovante_da_venda,
    estado_de_conciliacao,
    no_cartao,
    pendencias_da_venda,
)
from barra.dominio.grupo_financeiro.rateio import ler_recebedor_unico, planejar
from barra.dominio.grupo_financeiro.razao import VendaNoRazao, apurar
from barra.dominio.grupo_financeiro.temporada import VendaParaORazao, apurar_o_razao

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
BIANCA = UUID("22222222-2222-2222-2222-222222222222")
LARI = UUID("33333333-3333-3333-3333-333333333333")
JUJU = UUID("44444444-4444-4444-4444-444444444444")
DE_FORA = UUID("99999999-9999-9999-9999-999999999999")

MENSAGEM = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
FICHA = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
DIA = date(2026, 8, 20)

METADE = Decimal("50")
"""O `percentual_repasse` das quatro modelos ativas (reunião de 20/08). Snapshot, nunca constante
de código — aqui ele é dado de teste pelo mesmo motivo."""


def _cadastro() -> CadastroDeNomes:
    return CadastroDeNomes.de_linhas(
        modelos=[(YASMIN, "yasmin"), (BIANCA, "bianca"), (LARI, "lari"), (JUJU, "juju")],
        apelidos=[],
    )


def _venda(
    *,
    forma: FormaPagamento | None = None,
    modelo_id: UUID = YASMIN,
    recebido_por: UUID | None = None,
    comprovante_id: UUID | None = None,
) -> VendaRegistrada:
    return VendaRegistrada(
        id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        modelo_id=modelo_id,
        valor=Decimal("1000.00"),
        data=DIA,
        mensagem_id=MENSAGEM,
        forma_pagamento=forma,
        comprovante_id=comprovante_id,
        recebido_por_modelo_id=recebido_por,
    )


# ---------------------------------------------------------------------------------------------
# Ticket 11 — cartão virou débito, crédito e link
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "forma"),
    [
        ("foi no débito", "debito"),
        ("recebi, foi no crédito", "credito"),
        ("foi pelo link", "link"),
        ("recebi no cartão de crédito", "credito"),
        ("Débito", "debito"),
        ("foi pix", "pix"),
        ("dinheiro", "dinheiro"),
    ],
)
def test_as_cinco_formas_sao_lidas_cada_uma_pelo_seu_nome(texto: str, forma: str) -> None:
    """As três formas de cartão são valores distintos, nunca um "cartão" guarda-chuva.

    Escrever `debito` onde foi `credito` manda o operador procurar o dinheiro na adquirente errada,
    e ele só descobre na conciliação do fim do mês — quando ninguém lembra mais do atendimento.
    """
    fala = ler_fala_de_pagamento(texto)
    assert fala is not None
    assert fala.tipo == "resposta"
    assert fala.forma == forma


def test_cartao_sozinho_continua_sem_decidir_nada() -> None:
    """A FAMÍLIA não é forma, e não vira uma por palpite.

    Depois do desmembramento não existe mais o valor "cartão" na coluna, e escolher uma das três
    por frequência seria o palpite que este módulo recusa em todo lugar. O silêncio aqui é
    conhecido e é o que o teste de allowlist de `test_grupo_financeiro_promocao.py` já pinava —
    fechá-lo é devolver uma pergunta de uma palavra ("débito, crédito ou link?"), e perguntar é
    conduta da porta, não deste leitor.
    """
    assert ler_fala_de_pagamento("recebi em cartão") is None
    assert ler_fala_de_pagamento("foi na maquininha") is None


@pytest.mark.parametrize("texto", ["foi no débito ou no crédito?", "débito ou crédito"])
def test_duas_formas_na_mesma_frase_nao_decidem(texto: str) -> None:
    """Oferta é pergunta, não resposta — e a venda tem UMA coluna de forma."""
    fala = ler_fala_de_pagamento(texto)
    assert fala is not None
    assert fala.tipo == "pergunta"
    assert fala.forma is None


@pytest.mark.parametrize("forma", ["debito", "credito", "link"])
def test_cartao_nao_e_pix_nem_especie(forma: FormaPagamento) -> None:
    """Nem espera comprovante Pix, nem conta como espécie com a modelo.

    A prova da venda no cartão é o print da maquininha: ele não passa pelo OCR de comprovante, não
    abate venda em pix e não quita Cobrança da agência. Cobrar "o comprovante" de uma venda no
    crédito pediria um documento que este módulo não sabe ler — e a cobrança voltaria idêntica
    todo dia.
    """
    assert no_cartao(forma)
    assert not espera_comprovante(forma)
    assert not em_especie(forma)


@pytest.mark.parametrize("forma", ["pix", "dinheiro", None])
def test_o_que_nao_e_cartao_continua_nao_sendo(forma: FormaPagamento | None) -> None:
    assert not no_cartao(forma)


@pytest.mark.parametrize("forma", ["debito", "credito", "link"])
def test_venda_no_cartao_nao_entra_na_fila_de_comprovante(forma: FormaPagamento) -> None:
    """Sem comprovante e sem pendência: no que este módulo cobra, ela não deve nada."""
    venda = _venda(forma=forma)
    assert pendencias_da_venda(venda) == ()
    assert estado_de_conciliacao(venda) == "conciliada"


def test_o_bruto_do_cartao_nao_e_reduzido_por_taxa() -> None:
    """ADR-0045 §3: bruto = valor do card, e a comissão incide sobre ele.

    É o oposto de `financeiro/calculos.py`, que desconta a taxa antes do repasse (ADR-0013) — são
    duas contas diferentes, do grupo e do Módulo Financeiro, e unificá-las trocaria a regra que o
    dono ditou pela do outro módulo.
    """
    razao = apurar(
        [VendaNoRazao(valor=Decimal("1000.00"), bolso="dela", percentual_repasse_snapshot=METADE)]
    )

    assert razao.debitos == Decimal("1000.00")
    assert razao.creditos == Decimal("500.00")
    assert razao.saldo == Decimal("-500.00")


def test_o_bolso_do_cartao_vem_de_evidencia_e_nao_da_forma() -> None:
    """ADR-0047: a maquininha pode ser dela ou da casa, e o dono não sabe dizer de quem é.

    `nao_dito` é estado legítimo — entra na cobrança consolidada da manhã ao lado da forma que já
    é cobrada — e o razão o lê como `dela` por default conservador. O que não pode acontecer é a
    forma decidir o bolso: só `dinheiro` faz isso, porque espécie não tem outro bolso.
    """
    assert bolso_da_promocao("credito") == "nao_dito"
    assert bolso_da_promocao("debito") == "nao_dito"
    assert bolso_da_promocao("credito", comprovante_da_modelo=True) == "dela"
    assert bolso_da_promocao("dinheiro") == "dela"


def test_a_ficha_promovida_no_credito_nasce_no_credito() -> None:
    """A forma vem de quem a disser e atravessa a promoção inteira, sem virar "cartão"."""
    ficha = FichaDeAgendamento(
        id=FICHA,
        estado="aberta",
        mensagem_id=MENSAGEM,
        chave_conteudo="k",
        participantes=(ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00")),),
        cliente_nome="Igor",
        data=DIA,
    )

    promocao = planejar_promocao(
        ficha,
        modelo_id=YASMIN,
        origem_do_gesto="modelo",
        dia_do_gesto=DIA,
        forma="credito",
    )

    assert promocao is not None
    assert promocao.forma_pagamento == "credito"
    assert promocao.valor == Decimal("700.00")


# ---------------------------------------------------------------------------------------------
# Ticket 12 — deslocamento com recebedor e pagador
# ---------------------------------------------------------------------------------------------


def _ficha_com_transporte(
    *, antecipado: Decimal | None, transporte: Decimal | None
) -> FichaDeAgendamento:
    return FichaDeAgendamento(
        id=FICHA,
        estado="aberta",
        mensagem_id=MENSAGEM,
        chave_conteudo="k",
        participantes=(ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00")),),
        data=DIA,
        valor_antecipado=antecipado,
        valor_transporte=transporte,
        forma_antecipado="pix" if antecipado else None,
    )


def test_a_ficha_grava_os_dois_numeros() -> None:
    """`Valor antecipado` 100 e `Valor do transporte` 60 são dois fatos, não um.

    A diferença entre eles é margem — some se o sistema guardar um número só.
    """
    plano = planejar_deslocamento(
        _ficha_com_transporte(antecipado=Decimal("100.00"), transporte=Decimal("60.00"))
    )

    assert plano is not None
    assert plano.valor_antecipado == Decimal("100.00")
    assert plano.valor_transporte == Decimal("60.00")
    assert plano.forma_antecipado == "pix"
    assert plano.recebedor_do_antecipado == PARTE_PADRAO == "casa"


def test_uber_curto_pago_pela_casa_sem_antecipado_e_caso_valido() -> None:
    """*"Quando é muito perto, tipo 15 reais de Uber, eu pago"*: antecipado zero, transporte não.

    É o caso que a tabela de um valor só não sabia representar — e é ele que vira **crédito** dela
    quando quem paga é a modelo.
    """
    plano = planejar_deslocamento(
        _ficha_com_transporte(antecipado=None, transporte=Decimal("15.00"))
    )

    assert plano is not None
    assert plano.valor_antecipado == Decimal("0.00")
    assert plano.valor_transporte == Decimal("15.00")
    assert plano.registravel


def test_ficha_sem_transporte_nenhum_nao_vira_linha() -> None:
    """Os dois zerados não geram lançamento: a coluna tem CHECK, e o painel diria que houve
    transporte sem dizer quanto."""
    assert planejar_deslocamento(_ficha_com_transporte(antecipado=None, transporte=None)) is None


@pytest.mark.parametrize(
    ("antecipado", "recebedor", "transporte", "pagador", "debito", "credito"),
    [
        # Ela recebeu R$ 100, a casa pagou o Uber -> ela está com dinheiro da casa.
        ("100.00", "modelo", "100.00", "casa", "100.00", "0.00"),
        # A casa recebeu e a casa pagou -> o razão dela não muda em nada.
        ("100.00", "casa", "100.00", "casa", "0.00", "0.00"),
        # Ela recebeu R$ 100 e pagou R$ 60 -> sobrou 40 com ela, não 100.
        ("100.00", "modelo", "60.00", "modelo", "40.00", "0.00"),
        # Nada antecipado e ela pagou R$ 15 do próprio bolso -> a casa deve a ela.
        ("0.00", "casa", "15.00", "modelo", "0.00", "15.00"),
    ],
)
def test_os_quatro_casos_do_deslocamento_sao_uma_conta_so(
    antecipado: str, recebedor: str, transporte: str, pagador: str, debito: str, credito: str
) -> None:
    """`efeito = antecipado recebido por ela menos o transporte pago por ela`.

    Uma conta, e não quatro ramos: o dia em que aparecer um quinto arranjo (ela recebe e a casa
    paga metade) a conta já responde, enquanto a tabela precisaria de mais uma linha.
    """
    plano = planejar_deslocamento(
        _ficha_com_transporte(antecipado=Decimal(antecipado), transporte=Decimal(transporte)),
        recebedor_do_antecipado=recebedor,  # type: ignore[arg-type]
        pagador_do_transporte=pagador,  # type: ignore[arg-type]
    )
    assert plano is not None

    razao = apurar([plano.no_razao()])

    assert razao.debitos == Decimal(debito)
    assert razao.creditos == Decimal(credito)


def test_recebido_e_pago_pela_casa_nao_gera_linha_nenhuma() -> None:
    """Efeito zero não vira linha zerada: o extrato dela não fala de um dinheiro que não a tocou."""
    plano = planejar_deslocamento(
        _ficha_com_transporte(antecipado=Decimal("100.00"), transporte=Decimal("100.00"))
    )
    assert plano is not None

    assert apurar([plano.no_razao()]).linhas == ()


def test_o_deslocamento_nunca_entra_na_base_de_comissao() -> None:
    """Reembolso de custo não é serviço vendido (ADR-0045 §5).

    A comissão sai de R$ 1.000 (a venda), nunca de R$ 1.100 — e é por isso que o deslocamento é
    lançamento próprio, e não um campo somado ao valor da venda.
    """
    plano = planejar_deslocamento(
        _ficha_com_transporte(antecipado=Decimal("100.00"), transporte=Decimal("100.00")),
        recebedor_do_antecipado="modelo",
    )
    assert plano is not None

    razao = apurar(
        [
            VendaNoRazao(
                valor=Decimal("1000.00"), bolso="dela", percentual_repasse_snapshot=METADE
            ),
            plano.no_razao(),
        ]
    )

    comissao = [linha for linha in razao.linhas if linha.tipo == "comissao"]
    assert [linha.credito for linha in comissao] == [Decimal("500.00")]
    assert razao.debitos == Decimal("1100.00")


# ---------------------------------------------------------------------------------------------
# Ticket 13 — festinha: quem recebeu o dinheiro de todas
# ---------------------------------------------------------------------------------------------


def _festinha() -> AnuncioDeVenda:
    """Quatro modelos, R$ 1.000 cada uma — a fechinha do ADR-0043."""
    return AnuncioDeVenda(
        nomes=("yasmin", "bianca", "lari", "juju"),
        perfis=(("yasmin",), ("bianca",), ("lari",), ("juju",)),
        valor=Decimal("4000.00"),
        valor_por_modelo=Decimal("1000.00"),
        varias_modelos=True,
    )


def test_festinha_de_quatro_vira_quatro_linhas_no_valor_de_cada_uma() -> None:
    """ADR-0043: somar as quatro inventaria uma venda que ninguém fez; dar o total a uma daria o
    dinheiro das outras para ela. O faturamento individual é o que não pode sumir."""
    plano = planejar(_festinha(), cadastro=_cadastro(), dona_do_grupo=YASMIN)

    assert {linha.modelo_id for linha in plano.linhas} == {YASMIN, BIANCA, LARI, JUJU}
    assert [linha.valor for linha in plano.linhas] == [Decimal("1000.00")] * 4
    assert all(linha.recebido_por is None for linha in plano.linhas)


@pytest.mark.parametrize(
    "texto",
    [
        "a Yasmin recebeu tudo",
        "a yasmin recebeu por todas",
        "ficou tudo com a Yasmin",
        "o dinheiro de todas ficou com a yasmin",
    ],
)
def test_a_declaracao_de_que_uma_recebeu_por_todas_e_lida(texto: str) -> None:
    plano = planejar(_festinha(), cadastro=_cadastro(), dona_do_grupo=YASMIN)
    candidatas = [linha.modelo_id for linha in plano.linhas]

    assert ler_recebedor_unico(texto, cadastro=_cadastro(), candidatas=candidatas) == YASMIN


@pytest.mark.parametrize(
    "texto",
    [
        "a Yasmin recebeu",  # sem totalidade: é a resposta de pagamento de UMA venda
        "recebeu tudo",  # sem nome: não diz quem
        "quem recebeu tudo?",  # pergunta não declara nada
        "a Yasmin e a Bianca receberam tudo",  # duas mulheres é um fato sobre duas
        "a Yasmin recebeu tudo do cliente que chegou atrasado ontem à noite no hotel",  # não é
        "tudo certo com a Yasmin",  # sem verbo de recebimento
    ],
)
def test_o_que_nao_declara_recebedor_unico_nao_vira_palpite(texto: str) -> None:
    """A escrita que essa leitura dispara é cara e silenciosa — o débito do bruto INTEIRO muda de
    dona, e ninguém revisa uma coluna que o sistema preencheu sozinho."""
    plano = planejar(_festinha(), cadastro=_cadastro(), dona_do_grupo=YASMIN)
    candidatas = [linha.modelo_id for linha in plano.linhas]

    assert ler_recebedor_unico(texto, cadastro=_cadastro(), candidatas=candidatas) is None


def test_o_recebedor_carimba_todas_as_linhas_da_festinha() -> None:
    """Inclusive a dela: `recebido_por == modelo_id` é o mesmo que `None` para quem lê, e dois
    formatos para o mesmo fato é como uma das quatro linhas fica de fora."""
    plano = planejar(_festinha(), cadastro=_cadastro(), dona_do_grupo=YASMIN, recebido_por=YASMIN)

    assert {linha.recebido_por for linha in plano.linhas} == {YASMIN}


def test_recebedor_de_fora_da_venda_e_ignorado() -> None:
    """Apontar para quem não esteve lá mandaria o débito de R$ 4.000 para o extrato de outra
    pessoa, e as quatro que trabalharam ficariam limpas."""
    plano = planejar(_festinha(), cadastro=_cadastro(), dona_do_grupo=YASMIN, recebido_por=DE_FORA)

    assert all(linha.recebido_por is None for linha in plano.linhas)


def _vendas_da_festinha(recebedor: UUID | None) -> list[VendaParaORazao]:
    return [
        VendaParaORazao(
            id=UUID(f"0000000{i}-0000-0000-0000-000000000000"),
            modelo_id=modelo,
            valor=Decimal("1000.00"),
            data=DIA,
            bolso="dela",
            percentual_repasse_snapshot=METADE,
            recebido_por_modelo_id=recebedor,
        )
        for i, modelo in enumerate((YASMIN, BIANCA, LARI, JUJU), start=1)
    ]


def test_quem_recebeu_por_todas_carrega_o_debito_do_bruto_inteiro() -> None:
    """R$ 4.000 de débito e a comissão de R$ 500 dela — ADR-0045 §6."""
    razao = apurar_o_razao(modelo_id=YASMIN, vendas=_vendas_da_festinha(YASMIN))

    assert razao.debitos == Decimal("4000.00")
    assert razao.creditos == Decimal("500.00")
    assert razao.ela_deve == Decimal("3500.00")


@pytest.mark.parametrize("modelo", [BIANCA, LARI, JUJU])
def test_quem_nao_recebeu_fica_so_com_o_credito_da_comissao(modelo: UUID) -> None:
    """Ela trabalhou, tem R$ 500 a receber e não deve nada — o repasse entre modelos fica fora do
    sistema, e a casa fecha com cada uma."""
    razao = apurar_o_razao(modelo_id=modelo, vendas=_vendas_da_festinha(YASMIN))

    assert razao.debitos == Decimal("0.00")
    assert razao.a_casa_deve == Decimal("500.00")


def test_quem_nao_recebeu_nao_e_cobrada_de_comprovante() -> None:
    """O dinheiro dela foi para a amiga: não existe gesto capaz de fechar essa cobrança.

    A venda não some da conta — ela migra para a fila de abate de quem recebeu
    (`repo.vendas_pix_a_comprovar`, com `COALESCE(recebido_por_modelo_id, modelo_id)`).
    """
    dela = _venda(forma="pix", modelo_id=BIANCA, recebido_por=YASMIN)

    assert not espera_comprovante_da_venda(dela)
    assert pendencias_da_venda(dela) == ()


def test_quando_cada_uma_recebe_a_sua_o_comportamento_e_o_de_hoje() -> None:
    """Sem declaração, `recebido_por_modelo_id` é nulo e nada muda: pix ainda espera comprovante."""
    dela = _venda(forma="pix", modelo_id=BIANCA)

    assert espera_comprovante_da_venda(dela)
    assert [p.tipo for p in pendencias_da_venda(dela)] == ["comprovante"]

    razao = apurar_o_razao(modelo_id=BIANCA, vendas=_vendas_da_festinha(None))
    assert razao.debitos == Decimal("1000.00")
    assert razao.creditos == Decimal("500.00")
