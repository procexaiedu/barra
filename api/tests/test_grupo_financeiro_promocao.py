"""O pagamento promovendo a Ficha a Venda registrada, sem banco (spec 0006, ticket 07; ADR-0044).

O caso que dói: o card do Igor traz R$ 700, 1h, local próprio às 19h; às 22h a modelo escreve só
**"recebi, foi dinheiro"**. A venda nasce ali, herdando da ficha tudo que o telefonista já
digitou — e a modelo não é interrogada sobre nada disso.

O que este arquivo prova, e nenhuma linha dele precisa de banco:

1. **Sobre qual ficha** — a escada de sinais (`escolher_ficha`) é a mesma de `escolher_pagamento`:
   quote > nome dito > nome no contexto > única aberta > ambígua. Três fichas abertas e nada que
   aponte devolvem `ambigua`, nunca a mais recente: promover a errada cria uma venda com o cliente
   e o valor de OUTRO atendimento, e a certa continua aberta sendo cobrada.
2. **O que a venda herda** (`planejar_promocao`) — valor DELA (nunca o total da festinha), cliente,
   duração, local e a data do COMBINADO, não a do gesto. É a data que faz as duas portas do
   ADR-0046 §5 produzirem a mesma chave de conteúdo e a segunda não duplicar.
3. **A forma vem de quem a disser, nunca do card**: `forma_pagamento` da ficha é o combinado, e o
   combinado muda na porta do cliente.
4. **A origem do gesto é parâmetro** — a fala da modelo e o ✅ do telefonista (ticket 20) produzem
   o MESMO plano, e é isso que permite as duas portas terem uma escrita só.
5. **O bolso é resolvido por evidência** (ADR-0047), não herdado de cadastro: dinheiro é sempre
   dela, comprovante dela → casa é dela, e todo o resto é `nao_dito` — que é estado legítimo.

O que só o banco prova — a venda gravada, a ficha virando `realizada`, a idempotência entre as
duas portas pela chave de conteúdo, o recibo corrigível por quote — vive em
`tests/integracao/test_grupo_financeiro_promocao_na_porta.py`, com `needs_db`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from barra.dominio.grupo_financeiro.ficha import (
    FichaDeAgendamento,
    FormaDaFicha,
    OrigemDoAnuncio,
    ParticipanteDaFicha,
    PromocaoDaFicha,
    TipoDeAtendimento,
    TipoDeLocal,
    bolso_da_promocao,
    local_da_ficha,
    planejar_promocao,
)
from barra.dominio.grupo_financeiro.modelos import FormaPagamento, MensagemRegistrada
from barra.dominio.grupo_financeiro.pagamento import (
    PREFIXO_DO_DESEMPATE,
    escolher_ficha,
    ler_fala_de_pagamento,
    montar_pergunta_de_desempate_de_fichas,
    montar_recibo_da_promocao,
)

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
BIANCA = UUID("22222222-2222-2222-2222-222222222222")

DIA_DO_GESTO = date(2026, 8, 22)
DIA_DO_COMBINADO = date(2026, 8, 21)


def _ficha(
    *,
    cliente: str | None = "Igor",
    valor: Decimal | None = Decimal("700.00"),
    modelo_id: UUID = YASMIN,
    data_: date | None = DIA_DO_COMBINADO,
    duracao_minutos: int | None = None,
    tipo_atendimento: TipoDeAtendimento | None = None,
    tipo_local: TipoDeLocal | None = None,
    endereco: str | None = None,
    endereco_complemento: str | None = None,
    site: str | None = None,
    origem: OrigemDoAnuncio | None = None,
    forma_pagamento: FormaDaFicha | None = None,
) -> FichaDeAgendamento:
    return FichaDeAgendamento(
        id=uuid4(),
        estado="aberta",
        mensagem_id=uuid4(),
        chave_conteudo="x",
        participantes=(ParticipanteDaFicha(modelo_id=modelo_id, valor=valor, nome="Sofia"),),
        cliente_nome=cliente,
        data=data_,
        duracao_minutos=duracao_minutos,
        tipo_atendimento=tipo_atendimento,
        tipo_local=tipo_local,
        endereco=endereco,
        endereco_complemento=endereco_complemento,
        site=site,
        origem=origem,
        forma_pagamento=forma_pagamento,
    )


def _dita(texto: str, *, de_mim: bool = False) -> MensagemRegistrada:
    return MensagemRegistrada(
        id=uuid4(),
        texto=texto,
        de_mim=de_mim,
        recebida_em=datetime(2026, 8, 22, 22, 0, tzinfo=UTC),
    )


# --- sobre qual ficha ---------------------------------------------------------------------------


def test_uma_ficha_aberta_nao_tem_o_que_confundir() -> None:
    alvo = _ficha()

    escolha = escolher_ficha(texto="recebi, foi dinheiro", abertas=[alvo])

    assert escolha.motivo == "escolhida"
    assert escolha.ficha is alvo
    assert escolha.sinal == "unica"


def test_sem_ficha_aberta_nao_ha_o_que_promover() -> None:
    assert escolher_ficha(texto="recebi, foi dinheiro", abertas=[]).motivo == "sem_ficha_aberta"


def test_tres_fichas_abertas_e_nada_que_aponte_e_ambiguo() -> None:
    """O critério do ticket: vira UMA pergunta de desempate, nunca um palpite."""
    abertas = [_ficha(cliente="Igor"), _ficha(cliente="Ramon"), _ficha(cliente="Denis")]

    assert escolher_ficha(texto="recebi, foi dinheiro", abertas=abertas).motivo == "ambigua"


def test_o_nome_dito_na_propria_fala_escolhe_a_ficha() -> None:
    igor = _ficha(cliente="Igor")
    abertas = [igor, _ficha(cliente="Ramon"), _ficha(cliente="Denis")]

    escolha = escolher_ficha(texto="o do Igor foi dinheiro", abertas=abertas)

    assert escolha.ficha is igor
    assert escolha.sinal == "nome"


def test_o_nome_dito_no_contexto_recente_escolhe_a_ficha() -> None:
    ramon = _ficha(cliente="Ramon")
    abertas = [_ficha(cliente="Igor"), ramon]

    escolha = escolher_ficha(
        texto="foi pix",
        contexto=[_dita("o do Ramon de ontem"), _dita("bom dia")],
        abertas=abertas,
    )

    assert escolha.ficha is ramon
    assert escolha.sinal == "nome"


def test_o_quote_vence_o_nome_e_a_unica() -> None:
    citada = _ficha(cliente="Ramon")
    abertas = [_ficha(cliente="Igor"), citada]

    escolha = escolher_ficha(texto="o do Igor foi pix", abertas=abertas, ficha_citada=citada.id)

    assert escolha.ficha is citada
    assert escolha.sinal == "quote"


def test_quote_em_ficha_que_nao_esta_aberta_nao_decide_nada() -> None:
    """A ficha citada já foi promovida (ou cancelada): o quote aponta para fora da lista."""
    abertas = [_ficha(cliente="Igor"), _ficha(cliente="Ramon")]

    assert (
        escolher_ficha(texto="foi pix", abertas=abertas, ficha_citada=uuid4()).motivo == "ambigua"
    )


def test_a_fala_que_nomeia_duas_fichas_abertas_nao_desempata_sozinha() -> None:
    abertas = [_ficha(cliente="Igor"), _ficha(cliente="Ramon")]

    assert escolher_ficha(texto="Igor e Ramon foram pix", abertas=abertas).motivo == "ambigua"


def test_o_cliente_da_ficha_entra_na_allowlist_da_fala() -> None:
    """Sem o nome permitido, "o do Igor foi dinheiro" é descartado e a fila não anda.

    É o mesmo mecanismo que torna a cobrança da manhã respondível — só que os nomes agora vêm
    também das fichas abertas, que ainda não são venda nenhuma.
    """
    assert ler_fala_de_pagamento("o do Igor foi dinheiro") is None

    fala = ler_fala_de_pagamento("o do Igor foi dinheiro", nomes_de_cliente=["Igor"])

    assert fala is not None
    assert fala.tipo == "resposta"
    assert fala.forma == "dinheiro"


# --- a pergunta de desempate ---------------------------------------------------------------------


def test_a_pergunta_nomeia_as_candidatas_com_o_valor_dela() -> None:
    abertas = [
        _ficha(cliente="Igor", valor=Decimal("700.00")),
        _ficha(cliente="Ramon", valor=Decimal("900.00"), data_=DIA_DO_GESTO),
    ]

    pergunta = montar_pergunta_de_desempate_de_fichas(
        forma="dinheiro", candidatas=abertas, modelo_id=YASMIN
    )

    assert pergunta is not None
    assert pergunta.startswith(PREFIXO_DO_DESEMPATE)
    assert "Igor (R$ 700,00)" in pergunta
    assert "Ramon (R$ 900,00)" in pergunta
    # A mais recente primeiro: quem acabou de receber fala do atendimento de agora.
    assert pergunta.index("Ramon") < pergunta.index("Igor")


def test_a_pergunta_usa_o_valor_da_participante_e_nunca_o_total_da_festinha() -> None:
    """Numa festinha de R$ 2.000 com três modelos, dizer 2.000 para uma entrega a conta das outras."""
    festinha = FichaDeAgendamento(
        id=uuid4(),
        estado="aberta",
        mensagem_id=uuid4(),
        chave_conteudo="x",
        participantes=(
            ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00"), ordem=1),
            ParticipanteDaFicha(modelo_id=BIANCA, valor=Decimal("1300.00"), ordem=2),
        ),
        cliente_nome="Igor",
        data=DIA_DO_COMBINADO,
        valor_total=Decimal("2000.00"),
    )

    pergunta = montar_pergunta_de_desempate_de_fichas(
        forma="pix", candidatas=[festinha], modelo_id=YASMIN
    )

    assert pergunta is not None
    assert "R$ 700,00" in pergunta
    assert "2.000" not in pergunta
    assert "1.300" not in pergunta


def test_sem_candidata_nao_ha_pergunta() -> None:
    assert (
        montar_pergunta_de_desempate_de_fichas(forma="pix", candidatas=[], modelo_id=YASMIN) is None
    )


def test_a_pergunta_das_fichas_tem_o_mesmo_prefixo_da_pergunta_das_vendas() -> None:
    """É por ele que a porta reconhece, no log do grupo, que já perguntou — a tranca contra a
    metralhadora tem que valer para os dois alvos."""
    pergunta = montar_pergunta_de_desempate_de_fichas(
        forma="pix",
        candidatas=[_ficha(cliente="Igor"), _ficha(cliente="Ramon")],
        modelo_id=YASMIN,
    )

    assert pergunta is not None and pergunta.startswith(PREFIXO_DO_DESEMPATE)


# --- o que a venda herda da ficha ----------------------------------------------------------------


def _plano_do_igor(
    *, forma: FormaPagamento | None = None, comprovante_da_modelo: bool = False
) -> PromocaoDaFicha | None:
    ficha = _ficha(
        duracao_minutos=60,
        tipo_atendimento="interno",
        site="Barra Vips",
        origem="proprio",
    )
    return planejar_promocao(
        ficha,
        modelo_id=YASMIN,
        origem_do_gesto="modelo",
        dia_do_gesto=DIA_DO_GESTO,
        forma=forma,
        comprovante_da_modelo=comprovante_da_modelo,
    )


def test_a_venda_herda_tudo_que_o_telefonista_ja_digitou() -> None:
    plano = _plano_do_igor(forma="dinheiro")

    assert plano is not None
    assert plano.valor == Decimal("700.00")
    assert plano.cliente_nome == "Igor"
    assert plano.duracao_minutos == 60
    assert plano.local_atendimento == "no nosso local"
    assert plano.site == "Barra Vips"
    assert plano.origem == "proprio"
    assert plano.nome_da_modelo == "Sofia"
    assert plano.forma_pagamento == "dinheiro"


def test_a_data_e_a_do_combinado_e_nao_a_do_gesto() -> None:
    """É ela que faz o ✅ do dia seguinte cair na MESMA chave de conteúdo e não duplicar."""
    plano = _plano_do_igor(forma="dinheiro")

    assert plano is not None
    assert plano.data == DIA_DO_COMBINADO


def test_ficha_sem_data_e_datada_pelo_dia_do_gesto() -> None:
    """A ficha nascida de um comunicado não tem data — "a hora não precisa porque é uma prévia"."""
    plano = planejar_promocao(
        _ficha(data_=None),
        modelo_id=YASMIN,
        origem_do_gesto="modelo",
        dia_do_gesto=DIA_DO_GESTO,
        forma="pix",
    )

    assert plano is not None
    assert plano.data == DIA_DO_GESTO


def test_a_forma_vem_de_quem_a_disser_e_nunca_do_card() -> None:
    """O card diz o COMBINADO ("vai ser no pix"); o combinado muda na porta do cliente."""
    plano = planejar_promocao(
        _ficha(forma_pagamento="pix"),
        modelo_id=YASMIN,
        origem_do_gesto="modelo",
        dia_do_gesto=DIA_DO_GESTO,
        forma="dinheiro",
    )

    assert plano is not None
    assert plano.forma_pagamento == "dinheiro"


def test_sem_forma_dita_a_venda_nasce_com_a_pendencia_de_sempre() -> None:
    """O ✅ solto do ticket 20: a forma entra na cobrança consolidada da manhã, sem pergunta nova."""
    plano = planejar_promocao(
        _ficha(), modelo_id=YASMIN, origem_do_gesto="telefonista", dia_do_gesto=DIA_DO_GESTO
    )

    assert plano is not None
    assert plano.forma_pagamento is None
    assert plano.bolso == "nao_dito"


def test_a_origem_do_gesto_nao_muda_o_que_e_escrito() -> None:
    """As duas portas do ADR-0046 §5 produzem o mesmo fato — é o que permite uma escrita só."""
    pela_modelo = _plano_do_igor(forma="dinheiro")
    pelo_telefonista = planejar_promocao(
        _ficha(duracao_minutos=60, tipo_atendimento="interno", site="Barra Vips", origem="proprio"),
        modelo_id=YASMIN,
        origem_do_gesto="telefonista",
        dia_do_gesto=DIA_DO_GESTO,
        forma="dinheiro",
    )

    assert pela_modelo is not None and pelo_telefonista is not None
    assert pela_modelo.origem_do_gesto == "modelo"
    assert pelo_telefonista.origem_do_gesto == "telefonista"
    campos = ("valor", "data", "cliente_nome", "duracao_minutos", "forma_pagamento", "bolso")
    for campo in campos:
        assert getattr(pela_modelo, campo) == getattr(pelo_telefonista, campo)


def test_a_festinha_promove_o_valor_de_cada_uma_e_nao_o_total() -> None:
    festinha = FichaDeAgendamento(
        id=uuid4(),
        estado="aberta",
        mensagem_id=uuid4(),
        chave_conteudo="x",
        participantes=(
            ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00"), ordem=1, nome="Sofia"),
            ParticipanteDaFicha(modelo_id=BIANCA, valor=Decimal("1300.00"), ordem=2, nome="Duda"),
        ),
        cliente_nome="Igor",
        data=DIA_DO_COMBINADO,
        valor_total=Decimal("2000.00"),
    )

    dela = planejar_promocao(
        festinha, modelo_id=BIANCA, origem_do_gesto="modelo", dia_do_gesto=DIA_DO_GESTO, forma="pix"
    )

    assert dela is not None
    assert dela.valor == Decimal("1300.00")
    assert dela.modelo_id == BIANCA
    assert dela.nome_da_modelo == "Duda"


def test_ficha_sem_o_valor_dela_nao_vira_venda_de_zero() -> None:
    """A ficha não é receita e nasce podendo estar incompleta: o que falta é a cobrança da manhã."""
    assert (
        planejar_promocao(
            _ficha(valor=None),
            modelo_id=YASMIN,
            origem_do_gesto="modelo",
            dia_do_gesto=DIA_DO_GESTO,
            forma="dinheiro",
        )
        is None
    )


def test_modelo_que_nao_esta_na_ficha_nao_promove_nada() -> None:
    assert (
        planejar_promocao(
            _ficha(modelo_id=YASMIN),
            modelo_id=BIANCA,
            origem_do_gesto="modelo",
            dia_do_gesto=DIA_DO_GESTO,
            forma="pix",
        )
        is None
    )


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"tipo_atendimento": "interno"}, "no nosso local"),
        ({"tipo_atendimento": "externo"}, "saída"),
        ({"tipo_atendimento": "externo", "tipo_local": "motel"}, "saída · motel"),
        ({"tipo_local": "hotel"}, "hotel"),
        ({}, None),
    ],
)
def test_o_local_do_recibo_sai_dos_campos_do_card(
    campos: dict[str, Any], esperado: str | None
) -> None:
    assert local_da_ficha(_ficha(**campos)) == esperado


def test_o_endereco_nao_entra_no_recibo() -> None:
    """O recibo volta para o grupo; o endereço é onde a modelo mora e trabalha."""
    ficha = _ficha(
        tipo_atendimento="interno", endereco="Rua X 123", endereco_complemento="Apt 2706"
    )

    local = local_da_ficha(ficha)

    assert local is not None
    assert "Rua X" not in local and "2706" not in local


# --- o bolso, por evidencia (ADR-0047) ------------------------------------------------------------


def test_dinheiro_e_sempre_dela() -> None:
    assert bolso_da_promocao("dinheiro") == "dela"


def test_comprovante_dela_para_a_casa_e_dela() -> None:
    assert bolso_da_promocao("pix", comprovante_da_modelo=True) == "dela"


@pytest.mark.parametrize("forma", ["pix", None])
def test_sem_evidencia_o_bolso_e_nao_dito(forma: FormaPagamento | None) -> None:
    """ "Não dito" é estado legítimo (ADR-0047 §3): entra na cobrança da manhã, não vira palpite."""
    assert bolso_da_promocao(forma) == "nao_dito"


def test_o_bolso_nao_e_herdado_de_cadastro_nenhum() -> None:
    """`modelos.recebe_no_proprio_pix` não existe e não deve existir (ADR-0047 §1).

    O plano só sabe o que a evidência DESTA venda diz — não há parâmetro de modelo em lugar nenhum
    da assinatura, e é isso que impede o palpite estável que o Rossi negou.
    """
    plano = _plano_do_igor(forma="pix")

    assert plano is not None
    assert plano.bolso == "nao_dito"


def test_com_comprovante_da_modelo_a_promocao_nasce_com_o_bolso_dela() -> None:
    plano = _plano_do_igor(forma="pix", comprovante_da_modelo=True)

    assert plano is not None
    assert plano.bolso == "dela"


# --- o recibo -------------------------------------------------------------------------------------


def test_o_recibo_da_promocao_repete_o_que_o_telefonista_digitou() -> None:
    recibo = montar_recibo_da_promocao(
        nome_da_modelo="Sofia",
        valor=Decimal("700.00"),
        data=DIA_DO_COMBINADO,
        forma="dinheiro",
        cliente="Igor",
        duracao_minutos=60,
        local="no nosso local",
    )

    assert "Sofia R$ 700,00" in recibo
    assert "Cliente Igor" in recibo
    assert "1h" in recibo
    assert "no nosso local" in recibo
    assert "21/08" in recibo
    assert "corrige" in recibo


def test_o_recibo_marca_a_venda_em_dinheiro_como_especie_com_a_modelo() -> None:
    recibo = montar_recibo_da_promocao(
        nome_da_modelo="Sofia", valor=Decimal("700.00"), data=DIA_DO_COMBINADO, forma="dinheiro"
    )

    assert "em espécie com a modelo" in recibo


def test_sem_forma_dita_a_linha_da_forma_nao_aparece() -> None:
    recibo = montar_recibo_da_promocao(
        nome_da_modelo="Sofia", valor=Decimal("700.00"), data=DIA_DO_COMBINADO
    )

    assert "pix" not in recibo and "dinheiro" not in recibo
    assert "Sofia R$ 700,00" in recibo


# --- o verbo do aviso -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "forma"),
    [
        ("recebi, foi dinheiro", "dinheiro"),
        ("recebi foi pix", "pix"),
        ("recebi em dinheiro", "dinheiro"),
        ("já recebi, foi pix", "pix"),
        ("recebido em pix", "pix"),
    ],
)
def test_a_fala_do_aviso_da_modelo_e_lida(texto: str, forma: str) -> None:
    """A frase do ticket. Antes dele, "recebi" não estava na allowlist e a mensagem inteira era
    descartada em silêncio — a modelo avisava e a ficha seguia aberta."""
    fala = ler_fala_de_pagamento(texto)

    assert fala is not None
    assert fala.tipo == "resposta"
    assert fala.forma == forma


def test_recebi_sozinho_continua_nao_decidindo_nada() -> None:
    """Ele não responde "foi pix ou dinheiro?". Promover sem forma dita é a outra porta (ticket 20)."""
    assert ler_fala_de_pagamento("recebi") is None


@pytest.mark.parametrize(
    "texto",
    [
        "Pix erick",
        "Pode enviar nesse pix",
        "recebi o endereço",
        "Minha Chave Pix para transferência: +5571999999999",
        "recebi em cartão",
    ],
)
def test_o_verbo_novo_nao_abre_a_allowlist_para_o_resto_do_grupo(texto: str) -> None:
    """A allowlist continua FECHADA: uma palavra fora dela desqualifica a mensagem inteira.

    "recebi em cartão" fica de fora de propósito — cartão como forma de pagamento é o ticket 11, e
    aceitá-lo aqui gravaria uma forma que `FormaPagamento` ainda não sabe representar.
    """
    assert ler_fala_de_pagamento(texto) is None
