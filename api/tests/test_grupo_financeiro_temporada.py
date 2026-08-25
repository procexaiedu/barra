"""A Temporada e a persistencia do razao (ADR-0045 §7, ADR-0046 §6, ADR-0047, ticket 02).

O `razao.py` ja tem os seus proprios testes puros — o saldo com sinal, os quatro cenarios, o
arredondamento. O que se afirma AQUI e a outra metade, a que o banco alimenta: que uma linha de
`vendas_registradas` com `bolso` e `percentual_repasse_snapshot` vira o lancamento certo, que so o
comprovante de `fechamento` credita, que o recorte da Temporada filtra pela data do FATO, e que o
Extrato ganhou o saldo sem perder nenhuma coluna.

Sem banco: o leitor e puro e recebe read models. O que NAO da para afirmar sem `TEST_DATABASE_URL`
(e sem as migrations da onda 20260820 aplicadas) e o SQL do `repo.py` — as consultas novas nao sao
exercidas por nenhum teste desta casa.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from barra.dominio.grupo_financeiro.cobranca import CobrancaDaAgencia
from barra.dominio.grupo_financeiro.comprovante import Classificacao, ComprovanteDoGrupo
from barra.dominio.grupo_financeiro.fechamento import montar_extrato, montar_fala_do_fechamento
from barra.dominio.grupo_financeiro.modelos import VendaRegistrada
from barra.dominio.grupo_financeiro.razao import Bolso
from barra.dominio.grupo_financeiro.temporada import (
    DeslocamentoParaORazao,
    FechamentoDaTemporada,
    LancamentoManual,
    PagamentoDaTemporada,
    SentidoDoLancamento,
    Temporada,
    TipoDeLancamentoManual,
    TransferenciaParaORazao,
    VendaParaORazao,
    apurar_o_razao,
    lancamentos_do_razao,
)

MEIO = Decimal("50")
"""`percentual_repasse_snapshot`: 50%, o default de cadastro que a reuniao de 20/08 confirmou."""

MODELO = UUID("00000000-0000-0000-0000-0000000000aa")
OUTRA = UUID("00000000-0000-0000-0000-0000000000bb")

# A noite real do export: 12/08/2026, duas vendas de R$ 600,00 em pix.
DIA = date(2026, 8, 12)
TEMPORADA = Temporada(
    id=uuid4(),
    modelo_id=MODELO,
    cidade="Goiânia",
    data_inicio=date(2026, 8, 10),
    data_fim=date(2026, 8, 20),
)


def _venda(
    valor: str = "600.00",
    *,
    bolso: Bolso = "dela",
    percentual: Decimal | None = MEIO,
    modelo_id: UUID = MODELO,
    recebido_por: UUID | None = None,
    dia: date = DIA,
) -> VendaParaORazao:
    return VendaParaORazao(
        id=uuid4(),
        modelo_id=modelo_id,
        valor=Decimal(valor),
        data=dia,
        bolso=bolso,
        percentual_repasse_snapshot=percentual,
        recebido_por_modelo_id=recebido_por,
        cliente_nome="Cliente",
    )


def _duas_vendas(bolso: Bolso = "dela") -> list[VendaParaORazao]:
    return [_venda(bolso=bolso), _venda(bolso=bolso)]


def _transferencia(
    valor: str = "1200.00",
    *,
    classificacao: Classificacao = "fechamento",
    dia: date = DIA,
) -> TransferenciaParaORazao:
    return TransferenciaParaORazao(
        id=uuid4(), valor=Decimal(valor), data=dia, classificacao=classificacao
    )


def _cobranca(valor: str = "385.80", *, quitada: bool = False) -> CobrancaDaAgencia:
    return CobrancaDaAgencia(
        id=uuid4(),
        grupo_id=uuid4(),
        modelo_id=MODELO,
        mensagem_id=uuid4(),
        descricao="3RJ Suporte/Anúncio: 3 DIAS",
        valor=Decimal(valor),
        data=DIA,
        comprovante_id=uuid4() if quitada else None,
        quitada_em=datetime(2026, 8, 13, tzinfo=UTC) if quitada else None,
    )


def _manual(
    valor: str = "500.00",
    *,
    tipo: TipoDeLancamentoManual = "vale",
    sentido: SentidoDoLancamento = "debito",
    dia: date = DIA,
) -> LancamentoManual:
    return LancamentoManual(
        id=uuid4(),
        modelo_id=MODELO,
        tipo=tipo,
        sentido=sentido,
        valor=Decimal(valor),
        data=dia,
        origem="painel",
        descricao="adiantei pra ela",
    )


# --- os quatro cenarios de sinal, agora a partir do que o banco guarda -------------------------


def test_caso_real_do_export_a_casa_deve_600() -> None:
    """600 pix + 600 pix no bolso dela, comprovante de R$ 1.200,00 -> +600 (ADR-0045, evidencia)."""
    razao = apurar_o_razao(
        modelo_id=MODELO, vendas=_duas_vendas(), transferencias=[_transferencia()]
    )

    assert razao.saldo == Decimal("600.00")
    assert razao.a_casa_deve == Decimal("600.00")


def test_nao_transferiu_ela_deve_600() -> None:
    razao = apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas())

    assert razao.saldo == Decimal("-600.00")
    assert razao.ela_deve == Decimal("600.00")


def test_tudo_em_dinheiro_debita_igual() -> None:
    """Especie e `dela` como qualquer venda (ADR-0045 §2) — o espelho de "nao transferiu"."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas())

    assert razao.saldo == Decimal("-600.00")


def test_pix_da_empresa_a_casa_deve_600() -> None:
    """Bolso `empresa`: sem debito do bruto, mas a comissao credita do mesmo jeito."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas(bolso="empresa"))

    assert razao.saldo == Decimal("600.00")


def test_bolso_nao_dito_conta_como_dela() -> None:
    """ADR-0047 §4: o default do RAZAO e `dela` — errar para o lado que alguem confere."""
    assert apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas(bolso="nao_dito")).saldo == Decimal(
        "-600.00"
    )


# --- so a transferencia PARA A CASA credita ----------------------------------------------------


def test_comprovante_de_entrada_da_modelo_nao_credita() -> None:
    """Cliente pagando ELA e evidencia de bolso (ticket 21), nunca transferencia para a casa."""
    razao = apurar_o_razao(
        modelo_id=MODELO,
        vendas=_duas_vendas(),
        transferencias=[_transferencia(classificacao="entrada_da_modelo")],
    )

    assert razao.saldo == Decimal("-600.00")


def test_comprovante_de_cobranca_nao_credita_duas_vezes() -> None:
    """A cobranca quitada ja saiu do debito (so as ABERTAS entram); creditar o Pix a pagaria 2x."""
    razao = apurar_o_razao(
        modelo_id=MODELO,
        cobrancas=[_cobranca(quitada=True)],
        transferencias=[_transferencia("385.80", classificacao="cobranca")],
    )

    assert razao.saldo == Decimal("0.00")
    assert razao.linhas == ()


def test_comprovante_nao_classificado_e_ilegivel_ficam_fora() -> None:
    """Dinheiro que ninguem sabe de onde e ja e divergencia no extrato — nao vira credito calado."""
    for classificacao in ("nao_classificado", "ilegivel"):
        razao = apurar_o_razao(
            modelo_id=MODELO,
            transferencias=[_transferencia(classificacao=classificacao)],
        )
        assert razao.saldo == Decimal("0.00"), classificacao


# --- a cobranca da agencia ---------------------------------------------------------------------


def test_cobranca_aberta_debita_e_nao_abate_venda_nenhuma() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO,
        vendas=_duas_vendas(bolso="empresa"),
        cobrancas=[_cobranca()],
    )

    assert razao.saldo == Decimal("214.20")  # 600 de comissao - 385,80 de cobranca
    assert [linha.tipo for linha in razao.linhas] == ["comissao", "comissao", "cobranca"]


def test_cobranca_quitada_sai_do_razao() -> None:
    assert apurar_o_razao(modelo_id=MODELO, cobrancas=[_cobranca(quitada=True)]).linhas == ()


# --- o snapshot do percentual ------------------------------------------------------------------


def test_comissao_usa_o_snapshot_da_venda_e_nao_o_cadastro() -> None:
    """Mudar o percentual no cadastro nao pode reescrever temporada passada (ADR-0045 §3).

    O leitor so conhece `percentual_repasse_snapshot` — nao ha caminho por onde o cadastro atual
    da modelo chegue ate aqui, e e isso que o teste fixa.
    """
    antiga = _venda(percentual=Decimal("40"))
    nova = _venda(percentual=Decimal("60"))

    razao = apurar_o_razao(modelo_id=MODELO, vendas=[antiga, nova])

    creditos = [linha.credito for linha in razao.linhas if linha.tipo == "comissao"]
    assert creditos == [Decimal("240.00"), Decimal("360.00")]


def test_venda_sem_snapshot_nao_ganha_comissao() -> None:
    """Venda anterior a migration: sem snapshot, comissao ZERO — nunca 50% chutado no codigo."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=[_venda(percentual=None)])

    assert razao.saldo == Decimal("-600.00")
    assert [linha.tipo for linha in razao.linhas] == ["venda"]


# --- a festinha: quem recebeu por todas (ADR-0045 §6) ------------------------------------------


def test_quem_recebeu_por_todas_carrega_o_debito_sem_a_comissao_alheia() -> None:
    minha = _venda(modelo_id=MODELO)
    da_outra = _venda(modelo_id=OUTRA, recebido_por=MODELO)

    razao = apurar_o_razao(modelo_id=MODELO, vendas=[minha, da_outra])

    # 1.200 de debito (as duas vendas passaram pela mao dela) e so 300 de comissao (a dela).
    assert razao.debitos == Decimal("1200.00")
    assert razao.creditos == Decimal("300.00")
    assert razao.saldo == Decimal("-900.00")


def test_quem_nao_recebeu_fica_so_com_a_comissao() -> None:
    da_outra = _venda(modelo_id=OUTRA, recebido_por=MODELO)

    razao = apurar_o_razao(modelo_id=OUTRA, vendas=[da_outra])

    assert [linha.tipo for linha in razao.linhas] == ["comissao"]
    assert razao.saldo == Decimal("300.00")


def test_venda_de_outra_que_nao_passou_pela_mao_dela_nao_entra() -> None:
    alheia = _venda(modelo_id=OUTRA)

    assert lancamentos_do_razao(modelo_id=MODELO, vendas=[alheia]) == ()


# --- o deslocamento (ADR-0046 §6, ticket 12) ----------------------------------------------------


def _deslocamento(
    *,
    antecipado: str = "0.00",
    recebedor: str = "casa",
    transporte: str = "0.00",
    pagador: str = "casa",
    modelo_id: UUID = MODELO,
) -> DeslocamentoParaORazao:
    return DeslocamentoParaORazao(
        id=uuid4(),
        venda_id=uuid4(),
        modelo_id=modelo_id,
        data=DIA,
        valor_antecipado=Decimal(antecipado),
        valor_transporte=Decimal(transporte),
        recebedor_do_antecipado=recebedor,  # type: ignore[arg-type]
        pagador_do_transporte=pagador,  # type: ignore[arg-type]
    )


def test_deslocamento_recebido_por_ela_e_pago_pela_casa_debita() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO,
        deslocamentos=[_deslocamento(antecipado="100.00", recebedor="modelo")],
    )

    assert razao.saldo == Decimal("-100.00")


def test_deslocamento_recebido_e_pago_pela_casa_nao_toca_o_razao_dela() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO,
        deslocamentos=[_deslocamento(antecipado="100.00", transporte="60.00")],
    )

    assert razao.linhas == ()


def test_deslocamento_de_outra_modelo_nao_entra() -> None:
    """A tabela nao tem coluna de modelo: quem resolve e o JOIN, e o leitor confere de novo."""
    alheio = _deslocamento(antecipado="100.00", recebedor="modelo", modelo_id=OUTRA)

    assert lancamentos_do_razao(modelo_id=MODELO, deslocamentos=[alheio]) == ()


# --- vale e ajuste -----------------------------------------------------------------------------


def test_vale_debita() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO, vendas=_duas_vendas(bolso="empresa"), manuais=[_manual()]
    )

    assert razao.saldo == Decimal("100.00")  # 600 de comissao - 500 de vale
    assert [linha.tipo for linha in razao.linhas][-1] == "vale"


def test_ajuste_move_o_saldo_nos_dois_sentidos() -> None:
    """O saldo sai exato nos dois sentidos — a aproximacao de `_manual_no_razao` e so no rotulo."""
    debito = apurar_o_razao(
        modelo_id=MODELO, manuais=[_manual("80.00", tipo="ajuste", sentido="debito")]
    )
    credito = apurar_o_razao(
        modelo_id=MODELO, manuais=[_manual("80.00", tipo="ajuste", sentido="credito")]
    )

    assert debito.saldo == Decimal("-80.00")
    assert credito.saldo == Decimal("80.00")
    assert credito.linhas[0].descricao == "Ajuste: adiantei pra ela"


# --- o recorte da Temporada ---------------------------------------------------------------------


def test_recorte_da_temporada_filtra_pela_data_do_fato() -> None:
    """A temporada e recorte de LEITURA: quem esta fora do periodo nao entra na apuracao dela."""
    dentro = _venda(dia=date(2026, 8, 12))
    antes = _venda(dia=date(2026, 8, 9))
    depois = _venda(dia=date(2026, 8, 21))

    razao = apurar_o_razao(
        modelo_id=MODELO,
        vendas=[antes, dentro, depois],
        inicio=TEMPORADA.data_inicio,
        fim=TEMPORADA.data_fim,
    )

    assert [linha.origem_id for linha in razao.linhas] == [dentro.id, dentro.id]


def test_as_duas_pontas_da_temporada_entram() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO,
        vendas=[_venda(dia=TEMPORADA.data_inicio), _venda(dia=TEMPORADA.data_fim)],
        inicio=TEMPORADA.data_inicio,
        fim=TEMPORADA.data_fim,
    )

    assert razao.debitos == Decimal("1200.00")


def test_sem_pontas_o_saldo_e_corrente_e_continuo() -> None:
    """Sem `inicio`/`fim` nada e filtrado — o Fechamento de sempre, sem periodo estanque."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=[_venda(dia=date(2025, 1, 1)), _venda()])

    assert razao.debitos == Decimal("1200.00")


def test_temporada_conhece_o_proprio_periodo() -> None:
    assert TEMPORADA.dias == 11
    assert TEMPORADA.contem(date(2026, 8, 10))
    assert TEMPORADA.contem(date(2026, 8, 20))
    assert not TEMPORADA.contem(date(2026, 8, 21))
    assert TEMPORADA.aberta and not TEMPORADA.cancelada


# --- o fechamento da temporada: saldo x ja pago -------------------------------------------------


def _pagamento(valor: str) -> PagamentoDaTemporada:
    return PagamentoDaTemporada(
        id=uuid4(),
        modelo_id=MODELO,
        valor=Decimal(valor),
        data_pagamento=date(2026, 8, 21),
        temporada_id=TEMPORADA.id,
    )


def test_falta_pagar_e_o_saldo_menos_o_ja_pago() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO, vendas=_duas_vendas(), transferencias=[_transferencia()]
    )

    fechamento = FechamentoDaTemporada(
        temporada=TEMPORADA, razao=razao, pagamentos=(_pagamento("400.00"),)
    )

    assert fechamento.pago == Decimal("400.00")
    assert fechamento.falta_pagar == Decimal("200.00")
    assert fechamento.ela_deve == Decimal("0.00")


def test_pagamento_a_maior_vira_divida_dela() -> None:
    """ "Se ela ja recebeu, recebe a diferenca" — e a diferenca pode ser negativa (ADR-0045 §7)."""
    razao = apurar_o_razao(
        modelo_id=MODELO, vendas=_duas_vendas(), transferencias=[_transferencia()]
    )

    fechamento = FechamentoDaTemporada(
        temporada=TEMPORADA, razao=razao, pagamentos=(_pagamento("800.00"),)
    )

    assert fechamento.falta_pagar == Decimal("0.00")
    assert fechamento.ela_deve == Decimal("200.00")


def test_comprovante_atrasado_recalcula_a_temporada_ja_paga() -> None:
    """A temporada NAO congela (ADR-0045 §7): o Pix que chega depois muda o mesmo numero."""
    fechada = Temporada(
        id=TEMPORADA.id,
        modelo_id=MODELO,
        cidade=TEMPORADA.cidade,
        data_inicio=TEMPORADA.data_inicio,
        data_fim=TEMPORADA.data_fim,
        estado="fechada",
        fechada_em=datetime(2026, 8, 21, tzinfo=UTC),
    )
    pagamentos = (_pagamento("600.00"),)
    vendas = _duas_vendas()

    antes = FechamentoDaTemporada(
        temporada=fechada,
        razao=apurar_o_razao(modelo_id=MODELO, vendas=vendas, transferencias=[_transferencia()]),
        pagamentos=pagamentos,
    )
    atrasado = _transferencia("300.00", dia=date(2026, 8, 19))
    depois = FechamentoDaTemporada(
        temporada=fechada,
        razao=apurar_o_razao(
            modelo_id=MODELO,
            vendas=vendas,
            transferencias=[_transferencia(), atrasado],
            inicio=fechada.data_inicio,
            fim=fechada.data_fim,
        ),
        pagamentos=pagamentos,
    )

    assert antes.falta_pagar == Decimal("0.00")
    assert depois.falta_pagar == Decimal("300.00")


# --- o Extrato ganhou o saldo sem perder coluna nenhuma -----------------------------------------


def _venda_registrada(
    valor: str = "600.00", *, forma: str | None = "dinheiro", comprovante_id: UUID | None = None
) -> VendaRegistrada:
    return VendaRegistrada(
        id=uuid4(),
        modelo_id=MODELO,
        valor=Decimal(valor),
        data=DIA,
        mensagem_id=uuid4(),
        forma_pagamento=forma,  # type: ignore[arg-type]
        comprovante_id=comprovante_id,
    )


def _comprovante(valor: str = "1200.00") -> ComprovanteDoGrupo:
    return ComprovanteDoGrupo(
        id=uuid4(),
        grupo_id=uuid4(),
        mensagem_id=uuid4(),
        classificacao="fechamento",
        valor=Decimal(valor),
        data_transferencia=DIA,
        valor_abatido=Decimal(valor),
    )


def test_extrato_sem_razao_nao_fala_de_saldo() -> None:
    """`None` e "nao apurado": o caminho antigo continua exatamente como era."""
    extrato = montar_extrato(modelo_id=MODELO, vendas=[_venda_registrada()], comprovantes=[])

    assert extrato.razao is None
    assert extrato.saldo is None
    assert extrato.conciliado
    assert "saldo" not in montar_fala_do_fechamento(extrato).lower()


def test_extrato_com_saldo_a_favor_dela_diz_quanto_a_casa_deve() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO, vendas=_duas_vendas(), transferencias=[_transferencia()]
    )
    extrato = montar_extrato(
        modelo_id=MODELO,
        vendas=[_venda_registrada(forma="pix"), _venda_registrada(forma="pix")],
        comprovantes=[_comprovante()],
        razao=razao,
    )

    assert extrato.saldo == Decimal("600.00")
    assert "💰 A casa te deve R$ 600,00" in montar_fala_do_fechamento(extrato)


def test_especie_debita_no_razao_e_a_coluna_sobrevive() -> None:
    """ADR-0045 §2: "em especie" continua como recorte visual, e o dinheiro debita mesmo assim."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas())
    extrato = montar_extrato(
        modelo_id=MODELO,
        vendas=[_venda_registrada(), _venda_registrada()],
        comprovantes=[],
        razao=razao,
    )
    fala = montar_fala_do_fechamento(extrato)

    assert extrato.em_especie == Decimal("1200.00")
    assert extrato.vendido == extrato.comprovado + extrato.em_especie + extrato.a_comprovar + (
        extrato.sem_forma
    )
    assert "Em espécie com a modelo: R$ 1.200,00" in fala
    assert "💰 Você deve R$ 600,00 pra casa" in fala


def test_saldo_aberto_impede_o_tudo_conciliado() -> None:
    """Temporada inteira em dinheiro nao tem pendencia nenhuma — e a casa tem R$ 600 a receber."""
    razao = apurar_o_razao(modelo_id=MODELO, vendas=_duas_vendas())
    extrato = montar_extrato(
        modelo_id=MODELO,
        vendas=[_venda_registrada(), _venda_registrada()],
        comprovantes=[],
        razao=razao,
    )

    assert not extrato.pendencias and not extrato.divergencias
    assert not extrato.conciliado


def test_saldo_zerado_com_tudo_fechado_ainda_e_tudo_conciliado() -> None:
    razao = apurar_o_razao(
        modelo_id=MODELO,
        vendas=[_venda(bolso="empresa", percentual=None)],
    )
    comprovante = _comprovante("600.00")
    extrato = montar_extrato(
        modelo_id=MODELO,
        vendas=[_venda_registrada(forma="pix", comprovante_id=comprovante.id)],
        comprovantes=[comprovante],
        razao=razao,
    )

    assert razao.saldo == Decimal("0.00")
    assert extrato.conciliado
