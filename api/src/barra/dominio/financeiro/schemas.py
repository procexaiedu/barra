"""DTOs HTTP do Módulo Financeiro (ADR 0011).

Receita é projeção de `atendimentos` (sem tabela própria). Repasses pagos têm
tabela própria; ver `infra/sql/{ts}_financeiro.sql`. Despesas foram removidas
do escopo do módulo (ver nota de Update no ADR 0011).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# Repasse à modelo: enum SQL é forma_pagamento_enum (pix/dinheiro/cartao/outro);
# para repasse restringimos cartão via Pydantic (ADR 0011).
FormaPagamentoRepasse = Literal["pix", "dinheiro", "outro"]
FormaPagamentoReceita = Literal["pix", "dinheiro", "cartao", "outro"]

# Vocabulario da segunda fonte de receita (Grupo financeiro, spec 0005) redeclarado aqui em vez de
# importado de `dominio/grupo_financeiro/`: contexto nao importa modelo de contexto
# (dominio/CLAUDE.md). A copia nao pode divergir em silencio — o service converte o valor de la
# para o tipo daqui, entao um termo novo no dominio que nao chegue nesta linha quebra o mypy, nao
# a producao.
FormaPagamentoVendaRegistrada = Literal["pix", "dinheiro", "debito", "credito", "link"]
"""As CINCO formas (ADR-0046 §4, ticket 11): "cartao" foi desmembrado em debito, credito e
link, porque cada uma concilia no seu extrato. Cresceu por causa do tripwire descrito acima —
`grupo_financeiro.modelos.FormaPagamento` cresceu, e o mypy do service apontou esta linha."""
TipoDePendenciaVenda = Literal["forma_pagamento", "comprovante"]
EstadoDeConciliacaoVenda = Literal[
    "anulada", "aguardando_forma", "em_especie", "aguardando_comprovante", "conciliada"
]
TipoDeDivergenciaFechamento = Literal[
    "comprovante_sem_par",
    "credito_da_modelo",
    "pix_sem_venda_em_pix",
    "venda_comprovada_a_menor",
]


# ----------------------- Resumo / visão geral -------------------------------


class FinanceiroResumo(BaseModel):
    valor_bruto_brl: float
    valor_liquido_brl: float
    valor_repasse_calculado_brl: float
    valor_sem_repasse_definido_brl: float
    valor_repasse_pago_brl: float
    valor_saldo_repasse_brl: float
    fechamentos_total: int
    fechamentos_sem_snapshot: int


class JanelaComparacao(BaseModel):
    de: str
    ate: str


class ImportadosSemData(BaseModel):
    """Fechados sem data (sem evento `fechado_registrado`) — ficam fora do recorte
    por período. Bruto total, independente da janela e respeitando só o modelo."""

    contagem: int
    valor_bruto_brl: float


class ReceitaDasDuasFontes(BaseModel):
    """A receita real do periodo somando as DUAS fontes (ADR-0043).

    `atendimentos_fechados_brl` e a projecao de sempre (ADR-0011, hoje vazia em producao) e
    `vendas_registradas_brl` e o que a operacao anuncia nos Grupos financeiros. As duas sao
    disjuntas por construcao — o Grupo financeiro nunca fabrica Atendimento nem Cliente — entao o
    total e a soma pura, sem dedupe. Quando a IA de venda entrar em producao e a mesma venda puder
    entrar pelas duas portas, a precedencia entre fontes e decisao propria (ADR-0043).

    O bloco vem SEPARADO de `FinanceiroResumo` de proposito: repasse, liquido e comissao sao
    calculados sobre snapshot do Atendimento, e a Venda registrada nao tem snapshot nenhum
    (repasse/split ficam fora do sistema, por decisao do dono do produto). Somar a segunda fonte
    dentro do bruto do resumo quebraria em silencio a identidade `liquido = bruto - repasse`.
    """

    atendimentos_fechados_brl: float
    atendimentos_fechados_total: int
    vendas_registradas_brl: float
    vendas_registradas_total: int
    total_brl: float


class FinanceiroResumoResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    janela_comparacao: JanelaComparacao | None
    resumo: FinanceiroResumo
    resumo_anterior: FinanceiroResumo | None
    importados_sem_data: ImportadosSemData
    receita_das_duas_fontes: ReceitaDasDuasFontes
    receita_das_duas_fontes_anterior: ReceitaDasDuasFontes | None


# ----------------------- Receitas (projeção) --------------------------------


class ReceitaLinha(BaseModel):
    atendimento_id: UUID
    numero_curto: int
    fechado_em: str  # iso BRT
    modelo_id: UUID
    modelo_nome: str
    cliente_id: UUID
    cliente_nome: str
    forma_pagamento: FormaPagamentoReceita | None
    valor_bruto: float
    percentual_repasse_snapshot: float | None
    valor_repasse_calculado: float


class ReceitasListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[ReceitaLinha]
    next_cursor: str | None


# ----------------------- Vendas registradas (ADR-0043 / spec 0005) ----------
#
# A segunda fonte de receita, listada para AUDITORIA: e por aqui que o operador ve a operacao dos
# Grupos financeiros sem entrar em cada grupo. Nada aqui e editavel pelo painel — a Venda
# registrada se corrige no grupo, respondendo o recibo (spec 0005); o painel so le.


class VendaRegistradaLinha(BaseModel):
    """Uma Venda registrada como o operador a audita.

    Sem nenhum campo de Dados cadastrais da modelo (endereco operacional, chave Pix dela): aquilo
    e painel-only por outro motivo e mora no contexto da modelo, nao na linha de uma venda.
    `chave_pix_destino` aqui e o destino LIDO no comprovante desta venda, que e o dado que a flag
    manda conferir.
    """

    id: UUID
    modelo_id: UUID
    modelo_nome: str
    data: date
    valor: Decimal
    cliente_nome: str | None  # texto livre: nunca vira linha em `clientes` (ADR-0043)
    local_atendimento: str | None
    duracao_minutos: int | None
    forma_pagamento: FormaPagamentoVendaRegistrada | None
    conciliacao: EstadoDeConciliacaoVenda
    pendencias: list[TipoDePendenciaVenda]
    comprovante_id: UUID | None
    chave_pix_desconhecida: bool
    chave_pix_destino: str | None
    anulada_em: str | None  # iso; preenchido = a mensagem-fonte foi apagada no grupo
    mensagem_id: UUID  # origem auditavel: a mensagem do grupo que gerou a venda


class DivergenciaDoFechamento(BaseModel):
    """Dinheiro que o Fechamento da modelo nao consegue explicar (spec 0005, ticket 09).

    Vem por modelo e nao por venda: divergencia e da CONFERENCIA (vendido x comprovado), nao de
    uma linha — e e por isso que ela e um bloco a parte da lista, distinguivel da flag de chave
    desconhecida, que e da venda. Nunca trava nada: no grupo virou pergunta, aqui vira flag.
    """

    modelo_id: UUID
    modelo_nome: str
    tipo: TipoDeDivergenciaFechamento
    valor: Decimal
    data: date | None
    comprovante_id: UUID | None


class VendasRegistradasListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[VendaRegistradaLinha]
    next_cursor: str | None
    divergencias: list[DivergenciaDoFechamento]
    """Das modelos presentes NESTA pagina. O Fechamento e saldo corrente continuo (sem periodo),
    entao a divergencia listada aqui ignora o filtro de data de proposito: um comprovante sem par
    de julho continua sendo dinheiro sem explicacao em agosto."""


# ----------------------- Contexto do inspector ------------------------------


class ContextoCliente(BaseModel):
    """Agregados cross-modelo do cliente — painel-only (ADR 0008)."""

    cliente_id: UUID
    nome: str
    total_atendimentos: int
    total_fechados: int
    valor_total_brl: float
    ultima_atividade_iso: str | None
    modelos_distintas: int


class ContextoModeloDia(BaseModel):
    dia: str  # AAAA-MM-DD
    bruto: float


class ContextoModelo(BaseModel):
    """Agregados da modelo: posição no período + sparkline 30d (absolutos)."""

    modelo_id: UUID
    nome: str
    fechamentos_periodo: int
    valor_bruto_periodo: float
    valor_repasse_periodo: float
    serie_30d: list[ContextoModeloDia]


class ReceitaContextoResponse(BaseModel):
    """Contexto completo da linha de receita (inspector lateral)."""

    atendimento_id: UUID
    cliente: ContextoCliente
    modelo: ContextoModelo


# ----------------------- Repasses pagos -------------------------------------


class RepassePagoCriar(BaseModel):
    modelo_id: UUID
    data_pagamento: date
    valor: Decimal = Field(gt=0)
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None = None
    comprovante_object_key: str | None = None  # opcional; upload separado


class RepassePagoPatch(BaseModel):
    data_pagamento: date | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    forma_pagamento: FormaPagamentoRepasse | None = None
    observacao: str | None = None
    comprovante_object_key: str | None = None


class RepassePagoResponse(BaseModel):
    id: UUID
    modelo_id: UUID
    modelo_nome: str | None  # JOIN
    data_pagamento: date
    valor: Decimal
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None
    comprovante_object_key: str | None
    created_at: str
    updated_at: str


class RepassesPagamentosListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[RepassePagoResponse]
    next_cursor: str | None


# ----------------------- Repasses: saldo por modelo -------------------------


class SaldoModelo(BaseModel):
    modelo_id: UUID
    modelo_nome: str
    fechamentos_total: int
    valor_bruto: float
    valor_repasse_calculado: float
    valor_repasse_pago: float
    saldo: float  # calc - pago; pode ser negativo apos estorno (decisao T)
    fechamentos_sem_snapshot: int
    valor_sem_snapshot: float


class RepassesPorModeloResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[SaldoModelo]


# ----------------------- Preencher percentual retroativo --------------------


class AtendimentoSemSnapshotLinha(BaseModel):
    atendimento_id: UUID
    numero_curto: int
    fechado_em: str
    cliente_nome: str
    valor_bruto: float


class AtendimentosSemSnapshotResponse(BaseModel):
    modelo_id: UUID
    items: list[AtendimentoSemSnapshotLinha]


class PreencherRepasseRetroativoBody(BaseModel):
    atendimento_ids: list[UUID] = Field(min_length=1)
    percentual: Decimal = Field(ge=0, le=100)


class PreencherRepasseRetroativoResponse(BaseModel):
    atualizados: int


# ----------------------- Upload de comprovante ------------------------------


class ComprovanteUploadResponse(BaseModel):
    object_key: str
    put_url: str  # presigned PUT


class ComprovanteUrlResponse(BaseModel):
    url: str  # presigned GET, expira


# ----------------------- Série / visão geral analítica ----------------------


class FinanceiroSerieDia(BaseModel):
    """Agregado diário do período. Dias sem fechamento aparecem com zeros."""

    dia: str  # AAAA-MM-DD (BRT)
    bruto: float
    repasse_calculado: float
    liquido: float
    fechamentos: int


class FinanceiroMixForma(BaseModel):
    """Distribuição da receita bruta por forma de pagamento (apenas Fechado)."""

    forma_pagamento: str  # pix | dinheiro | cartao | outro | indefinido
    valor_bruto: float
    fechamentos: int


class FinanceiroTopModelo(BaseModel):
    """Top contribuintes do período, ordenado por bruto decrescente."""

    modelo_id: UUID
    modelo_nome: str
    bruto: float
    liquido: float
    repasse_calculado: float
    fechamentos: int


class FinanceiroSerieResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    serie_diaria: list[FinanceiroSerieDia]
    mix_forma_pagamento: list[FinanceiroMixForma]
    top_modelos: list[FinanceiroTopModelo]


# ----------------------- Comissão de vendedor (ADR 0012) --------------------


class SaldoVendedor(BaseModel):
    """Saldo de comissão por vendedor (espelha SaldoModelo do repasse)."""

    vendedor_id: UUID
    vendedor_nome: str
    nivel: str
    fechamentos_total: int
    valor_servico: float  # base liquida de taxa de cartao (ADR 0013)
    valor_comissao_calculada: float
    valor_comissao_paga: float
    saldo: float  # calc - pago; pode ser negativo apos estorno


class ComissoesPorVendedorResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[SaldoVendedor]


# Pagamentos de Comissão de vendedor (ADR 0012) — espelha os DTOs de repasse pago,
# trocando o eixo de modelo por vendedor. A forma reaproveita FormaPagamentoRepasse
# (pix/dinheiro/outro): paga-se a pessoa do vendedor, nunca via cartão.
class ComissaoPagaCriar(BaseModel):
    vendedor_id: UUID
    data_pagamento: date
    valor: Decimal = Field(gt=0)
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None = None
    comprovante_object_key: str | None = None  # opcional; upload separado (P1)


class ComissaoPagaPatch(BaseModel):
    data_pagamento: date | None = None
    valor: Decimal | None = Field(default=None, gt=0)
    forma_pagamento: FormaPagamentoRepasse | None = None
    observacao: str | None = None
    comprovante_object_key: str | None = None


class ComissaoPagaResponse(BaseModel):
    id: UUID
    vendedor_id: UUID
    vendedor_nome: str | None  # JOIN
    data_pagamento: date
    valor: Decimal
    forma_pagamento: FormaPagamentoRepasse
    observacao: str | None
    comprovante_object_key: str | None
    created_at: str
    updated_at: str


class ComissoesPagamentosListaResponse(BaseModel):
    filtro_aplicado: dict[str, Any]
    items: list[ComissaoPagaResponse]
    next_cursor: str | None


# ---------------- Razão da modelo, Temporada e conferência (ticket 04) -------
#
# O gestor pediu duas telas na reunião de 20/08: o "financeiro dos telefonistas"
# (`/financeiro`, todas as temporadas com o saldo de cada modelo num lugar só) e o
# "financeiro individual" (a ficha da modelo com o extrato dela). Os DTOs abaixo servem as duas
# e nada mais — nenhum deles é escrita, e nenhum toca `/atendimentos` (ADR-0043 segue valendo:
# nenhum Atendimento é fabricado).
#
# ⚠️ NENHUM destes DTOs carrega comissão de telefonista (ADR-0048, última consequência): são duas
# contas de pessoas diferentes, e a modelo lê esta tela junto com o gestor.

# As cinco formas que a operação usa de fato (ADR-0046 §4) — "cartão" deixou de ser uma forma só.
# O campo `forma` da conferência é `str` e não `Literal` de propósito: se um dado antigo trouxer
# um termo fora deste vocabulário, a conferência tem que MOSTRÁ-LO, não estourar 500 no meio de
# uma tela de leitura. `sem_forma` é a venda cuja forma ninguém disse ainda.
FORMAS_DA_VENDA_REGISTRADA: tuple[str, ...] = ("pix", "dinheiro", "debito", "credito", "link")

EstadoDaTemporada = Literal["aberta", "fechada", "cancelada"]

TipoDaLinhaDoExtrato = Literal[
    "venda", "comissao", "transferencia", "cobranca", "vale", "ajuste", "deslocamento"
]

OrigemDaLinhaDoExtrato = Literal[
    "venda_registrada",
    "comprovante_do_grupo",
    "cobranca_da_agencia",
    "razao_lancamento_manual",
    "deslocamento_da_venda",
]


class SaldoDoRazao(BaseModel):
    """O número com sinal que o gestor pede, e as duas somas que o explicam (ADR-0045 §1).

    `saldo_brl` positivo = a casa deve a ela; negativo = ela deve à casa. `a_casa_deve_brl` e
    `ela_deve_brl` são o mesmo número já lido para cada lado, para a tela não precisar decidir.

    `pago_brl` NÃO está dentro de `saldo_brl`. A Temporada não congela cálculo (ADR-0045 §7): o
    saldo segue derivado dos fatos, e o que já foi pago aparece ao lado, como o ADR o descreve —
    "a diferença contra o já pago aparece como 'falta pagar R$ X' (ou crédito, se pagou a mais)".
    """

    debitos_brl: float
    creditos_brl: float
    saldo_brl: float
    a_casa_deve_brl: float
    ela_deve_brl: float
    pago_brl: float
    falta_pagar_brl: float


class LinhaDoExtrato(BaseModel):
    """Uma linha do extrato dela, com a ORIGEM à vista.

    Uma venda no bolso dela rende DUAS linhas — o débito do bruto e o crédito da comissão — e é
    isso que explica por que o saldo deu o que deu.
    """

    tipo: TipoDaLinhaDoExtrato
    origem: OrigemDaLinhaDoExtrato
    origem_id: UUID | None
    data: date
    descricao: str | None
    debito_brl: float
    credito_brl: float


class PagamentoDaModeloLinha(BaseModel):
    """Um repasse já pago (`financeiro_repasses_pagos`). Fora do saldo, ao lado dele."""

    id: UUID
    data: date
    valor_brl: float
    forma_pagamento: str
    observacao: str | None
    temporada_id: UUID | None


class ConferenciaFormaLinha(BaseModel):
    forma: str
    vendas: int
    valor_brl: float


class ConferenciaPorFormaResponse(BaseModel):
    """A conferência pix / dinheiro / débito / crédito / link (+ `sem_forma`) e o vendido total."""

    de: date | None
    ate: date | None
    formas: list[ConferenciaFormaLinha]
    vendas: int
    vendido_brl: float


class SinalizacaoDoExtrato(BaseModel):
    """Pendência ou divergência: contada e somada, nunca bloqueante.

    Pendência é fila ("ninguém disse a forma ainda"), não erro — `bolso = 'nao_dito'` é estado
    legítimo (ADR-0047 §3). Divergência é o saldo contando de um jeito que alguém precisa olhar.
    """

    tipo: str
    quantidade: int
    valor_brl: float


class TemporadaLinha(BaseModel):
    id: UUID
    modelo_id: UUID
    modelo_nome: str
    cidade: str
    data_inicio: date
    data_fim: date
    estado: EstadoDaTemporada
    observacao: str | None
    fechada_em: str | None
    vendas: int
    vendido_brl: float
    saldo: SaldoDoRazao
    pendencias: int
    """Quantas pendências abertas o período tem — o badge, não a lista (ela mora no extrato)."""


class TemporadasListaResponse(BaseModel):
    items: list[TemporadaLinha]
    total_a_casa_deve_brl: float
    total_ela_deve_brl: float
    total_falta_pagar_brl: float


class ExtratoDaModeloResponse(BaseModel):
    """O "financeiro individual": o extrato da modelo, com a origem de cada lançamento.

    Sem recorte (`de`/`ate`/`temporada_id` nulos) é o saldo corrente contínuo de sempre.
    """

    modelo_id: UUID
    modelo_nome: str
    percentual_repasse: float | None
    """O percentual de CADASTRO (default do próximo snapshot), nunca o já congelado nas vendas."""
    de: date | None
    ate: date | None
    temporada_id: UUID | None
    temporada_cidade: str | None
    temporada_estado: EstadoDaTemporada | None
    saldo: SaldoDoRazao
    conferencia: ConferenciaPorFormaResponse
    linhas: list[LinhaDoExtrato]
    pagamentos: list[PagamentoDaModeloLinha]
    pendencias: list[SinalizacaoDoExtrato]
    divergencias: list[SinalizacaoDoExtrato]


# ----------------------- Vale e fechamento da temporada (ticket 05) ---------
#
# Os DTOs das duas ações que MOVEM DINHEIRO no painel: lançar o vale adiantado ("tem que pagar uma
# conta de 500 reais, eu adianto") e fechar a temporada registrando o pagamento feito à modelo.
#
# ⚠️ Fechar é ação do PAINEL, nunca frase no grupo (ADR-0045 §8) — a modelo está dentro do grupo, e
# uma frase interpretada errada ali moveria dinheiro de verdade.
#
# ⚠️ Nenhum destes DTOs carrega saldo GRAVADO (ADR-0045 §7). `FechamentoDaTemporadaResponse` é
# apurado na hora, a cada leitura: um comprovante que chegar depois de a temporada estar paga
# muda o mesmo objeto, e a diferença contra o já pago aparece em `saldo.falta_pagar_brl`. Não
# existe reabertura porque nunca houve congelamento.

TipoDoLancamentoManual = Literal["vale", "ajuste"]
SentidoDoLancamentoManual = Literal["debito", "credito"]
OrigemDoLancamentoManual = Literal["painel", "grupo"]


class TemporadaCriar(BaseModel):
    """Abrir a temporada: a viagem da modelo para uma cidade, que é a unidade de pagamento."""

    modelo_id: UUID
    cidade: str = Field(min_length=1, max_length=120)
    data_inicio: date
    data_fim: date
    observacao: str | None = None

    @model_validator(mode="after")
    def _periodo_valido(self) -> "TemporadaCriar":
        if self.data_fim < self.data_inicio:
            raise ValueError("data_fim não pode ser anterior a data_inicio")
        return self


class TemporadaResponse(BaseModel):
    """A temporada como cadastro — deliberadamente **sem número de dinheiro**.

    Cidade e datas são o recorte; o saldo é derivado e mora em `TemporadaLinha`/
    `FechamentoDaTemporadaResponse`, sempre recalculado.
    """

    id: UUID
    modelo_id: UUID
    modelo_nome: str
    cidade: str
    data_inicio: date
    data_fim: date
    estado: EstadoDaTemporada
    observacao: str | None
    fechada_em: str | None


class LancamentoManualCriar(BaseModel):
    """O vale adiantado (ou o ajuste) lançado pelo gestor no painel.

    `valor` é SEMPRE positivo e a direção mora em `sentido` — número negativo em campo de dinheiro
    é a forma mais barata de somar errado em silêncio. Vale é sempre `debito`: adiantamento é
    dinheiro que ela já pegou.

    ⚠️ "Ficou com ela", dito sobre uma venda, **não é vale** (ADR-0047 §5): é a venda com
    `bolso = 'dela'` mais a ausência da transferência, e o razão já dá o número certo. Lançar um
    vale além disso contaria o mesmo dinheiro duas vezes.
    """

    modelo_id: UUID
    tipo: TipoDoLancamentoManual = "vale"
    sentido: SentidoDoLancamentoManual = "debito"
    valor: Decimal = Field(gt=0)
    data: date
    descricao: str | None = None
    temporada_id: UUID | None = None

    @model_validator(mode="after")
    def _vale_e_debito(self) -> "LancamentoManualCriar":
        # Mesma regra do CHECK `razao_lancamentos_manuais_vale_e_debito`, aqui para virar 422 com
        # nome de campo em vez de erro de integridade sem explicação.
        if self.tipo == "vale" and self.sentido != "debito":
            raise ValueError("vale é sempre débito — adiantamento é dinheiro que ela já pegou")
        return self


class LancamentoManualResponse(BaseModel):
    """Um vale/ajuste do razão, com a ORIGEM à vista.

    `origem` distingue o vale que o gestor digitou (`painel`, com `created_by`) do que o agente
    leu no grupo (`grupo`, com `mensagem_id` e recibo corrigível). Os dois debitam igual; só um
    tem alguém deste lado responsável pelo número.
    """

    id: UUID
    modelo_id: UUID
    tipo: TipoDoLancamentoManual
    sentido: SentidoDoLancamentoManual
    valor_brl: float
    data: date
    descricao: str | None
    origem: OrigemDoLancamentoManual
    temporada_id: UUID | None
    anulado_em: str | None


class FecharTemporadaBody(BaseModel):
    """O gesto de fechar: registrar o pagamento feito e marcar a temporada.

    `valor` nulo fecha **sem** pagamento — é o caso normal quando ela é que deve à casa, e obrigar
    um pagamento de R$ 0 inventaria um fato que não aconteceu. `marcar_fechada=False` registra só
    o pagamento (adiantamento no meio da temporada, ou a diferença que faltou depois).

    ⚠️ Fechar **não congela** nada (ADR-0045 §7): grava `estado` e `fechada_em`, que são marca de
    rotina. O saldo continua derivado, e comprovante que chegar depois muda o número sem ninguém
    reabrir coisa nenhuma.
    """

    valor: Decimal | None = Field(default=None, gt=0)
    data_pagamento: date | None = None
    forma_pagamento: FormaPagamentoRepasse = "pix"
    observacao: str | None = None
    comprovante_object_key: str | None = None
    marcar_fechada: bool = True

    @model_validator(mode="after")
    def _algum_gesto(self) -> "FecharTemporadaBody":
        if self.valor is None and not self.marcar_fechada:
            raise ValueError("nada a fazer: informe um valor a pagar ou marque a temporada")
        return self


class FechamentoDaTemporadaResponse(BaseModel):
    """A tela de fechar temporada — e a resposta de quem acabou de fechá-la.

    É o mesmo DTO nas duas pontas de propósito: o `GET` mostra o que o gestor está prestes a
    fazer, e o `POST` devolve o estado RECALCULADO depois de fazer. Um comprovante de R$ 600 que
    chegar amanhã muda `saldo.falta_pagar_brl` no próximo `GET`, sem reabertura.

    As **pendências abertas** vêm na resposta para serem lidas ANTES de confirmar (é o critério do
    ticket): venda sem forma, venda sem o bolso dito, cobrança em aberto, comprovante retido. Elas
    não travam o fechamento — o gestor decide fechar assim mesmo.
    """

    temporada: TemporadaResponse
    saldo: SaldoDoRazao
    sugestao_de_pagamento_brl: float
    """`falta_pagar_brl` sem o lado negativo: quanto a casa ainda deve. Zero quando ela é que deve
    (nesse caso não há pagamento a fazer, e o fechamento é só a marca)."""
    vendas: int
    vendido_brl: float
    pendencias: list[SinalizacaoDoExtrato]
    divergencias: list[SinalizacaoDoExtrato]
    pagamentos: list[PagamentoDaModeloLinha]
    vales: list[LancamentoManualResponse]


# --------------------- Telefonistas (cadastro do vendedor) -------------------
#
# A aba **Telefonistas**, ao lado de Modelos (ADR-0048). "Telefonista" é como o dono chama o
# **Vendedor** quando fala do grupo financeiro — a tabela continua sendo `barravips.vendedores`, e
# não existe entidade nova. O cadastro básico já tinha porta em `/v1/vendedores`; o que faltava era
# o número que ele pediu para poder mexer.


PERCENTUAL_COMISSAO_PADRAO = Decimal("7.00")
"""A referência que o dono deu (*"7%"*) e o DEFAULT da coluna. Vale para telefonista NOVO; quem já
existia manteve o percentual do nível (4/5/6) pelo backfill — 7 não é reprecificação retroativa."""

PERCENTUAL_COMISSAO_FAIXA_MIN = Decimal("1")
PERCENTUAL_COMISSAO_FAIXA_MAX = Decimal("10")
"""A faixa **operacional** de 1-10% (ADR-0048). Não é validação: o CHECK do banco é 0..100 e o
Pydantic abaixo também, porque o próprio dono divagou *"ou até 100%"*. Estes dois números existem
para a tela AVISAR que o valor saiu do usual, nunca para recusar."""


class TelefonistaResponse(BaseModel):
    """Um telefonista como a aba de cadastro o mostra: nome, percentual, ativo e o JID.

    `whatsapp_jid` vem junto porque telefonista sem JID nunca ganha comissão de venda anunciada no
    grupo — o vínculo com a venda é o autor da mensagem (ADR-0048 §5), e o resolver é closed-world:
    autor que não está aqui vira venda sem vendedor, sem comissão e sem erro. Isso precisa ser
    visível no cadastro, não descoberto no fim do mês.
    """

    id: UUID
    nome: str
    percentual_comissao: float
    ativo: bool
    whatsapp_jid: str | None


class TelefonistasListaResponse(BaseModel):
    items: list[TelefonistaResponse]


class TelefonistaCriar(BaseModel):
    """Cadastrar o telefonista. `percentual_comissao` omitido = 7% (a referência do dono).

    O `nivel` do ADR-0012 não entra: ele sobrevive só como rótulo de cadastro e parou de ser
    consultado no cálculo (ADR-0048 §1). Quem quiser mexer nele continua tendo `/v1/vendedores`.
    """

    nome: str = Field(min_length=1, max_length=200)
    percentual_comissao: Decimal = Field(default=PERCENTUAL_COMISSAO_PADRAO, ge=0, le=100)
    whatsapp_jid: str | None = None


class TelefonistaPatch(BaseModel):
    """Patch parcial (`exclude_unset`): só o que veio é tocado.

    `ativo=false` é a desativação, não exclusão — `financeiro_comissoes_pagas` referencia o
    vendedor com `ON DELETE RESTRICT`, e apagar apagaria histórico de pagamento.

    ⚠️ Mexer no percentual **reprojeta a comissão inteira**, inclusive a de vendas já feitas: a
    comissão do telefonista é projeção sem snapshot (ADR-0048 §6), ao contrário do
    `percentual_repasse_snapshot` da modelo.
    """

    nome: str | None = Field(default=None, min_length=1, max_length=200)
    percentual_comissao: Decimal | None = Field(default=None, ge=0, le=100)
    ativo: bool | None = None
    whatsapp_jid: str | None = None
    """`null` aqui APAGA o vínculo (a coluna é nullable) — é o único campo em que `null` é gesto, e
    não "não mexa"."""


# ----------------------- Chaves Pix: o registro tipado (ADR-0049, ticket 02) -------------------

PapelDaChavePix = Literal["casa", "modelo", "telefonista", "terceiro"]
"""De quem e a chave — `barravips.papel_da_chave_enum`.

Redeclarado aqui em vez de importado de `dominio/grupo_financeiro/repo.py`, pela mesma regra de
`FormaPagamentoVendaRegistrada` acima: contexto nao importa modelo de contexto. A divergencia nao
passa em silencio — a rota converte o valor do repo para este tipo, e um papel novo no dominio
quebra o mypy nesta linha antes de quebrar a tela.

`desconhecida`, a quinta resposta do ADR-0049 §1, NAO esta aqui: ela e a ausencia de cadastro, e
nao existe linha para devolve-la.
"""


class ChavePixResponse(BaseModel):
    """Uma chave do registro, do jeito que a aba **Chaves Pix** a mostra.

    `modelo_nome` / `vendedor_nome` vem resolvidos porque a tela e lida por quem nao sabe UUID de
    cor; sao `null` sempre que o papel nao pede dono (`casa`, `terceiro`).

    ⚠️ `chave` vai inteira para o painel. Ela e dado operacional da casa, na mesma aba em que o
    gestor a cadastrou — mascarar aqui impediria justamente a conferencia "e esta mesmo a chave que
    apareceu no comprovante?", que e para o que a tela existe.
    """

    id: UUID
    chave: str
    chave_normalizada: str
    """A forma de comparacao (sem espaco, pontuacao e sinal, minusculo) — a MESMA que o OCR usa.
    Vai para a tela porque e ela que explica por que duas grafias sao "a mesma chave"."""
    papel: PapelDaChavePix
    modelo_id: UUID | None
    modelo_nome: str | None
    vendedor_id: UUID | None
    vendedor_nome: str | None
    titular: str | None
    descricao: str | None
    padrao: bool
    """A UMA chave da casa que a operacao usa por default. No maximo uma em toda a lista."""
    ativo: bool


class ChavesPixListaResponse(BaseModel):
    items: list[ChavePixResponse]


def validar_papel_x_dono_da_chave(
    papel: PapelDaChavePix | None,
    modelo_id: UUID | None,
    vendedor_id: UUID | None,
) -> None:
    """A mesma regra do CHECK `chaves_pix_conhecidas_papel_x_dono`, um passo antes do banco.

    Existe em duplicata de proposito: o CHECK e a invariante (nenhum caminho a fura), e esta funcao
    e a mensagem em portugues. Sem ela o gestor que erra o formulario recebe um 500 de constraint.
    """
    if papel == "modelo" and modelo_id is None:
        raise ValueError("Chave com papel `modelo` precisa dizer de qual modelo.")
    if papel == "telefonista" and vendedor_id is None:
        raise ValueError("Chave com papel `telefonista` precisa dizer de qual telefonista.")
    if papel != "modelo" and modelo_id is not None:
        raise ValueError("So chave com papel `modelo` aponta para uma modelo.")
    if papel != "telefonista" and vendedor_id is not None:
        raise ValueError("So chave com papel `telefonista` aponta para um telefonista.")


class ChavePixCriar(BaseModel):
    """Cadastrar uma chave. `papel` e obrigatorio: nao existe chave sem dono declarado.

    Nao ha DEFAULT de papel no banco nem aqui, e e proposital (ADR-0049 §2): um default `casa`
    faria a proxima insercao distraida chamar de casa a chave de um terceiro, que e exatamente a
    confusao que este cadastro existe para acabar.

    A mesma modelo pode ter varias chaves — CPF, telefone, aleatoria, e ela troca de banco.
    """

    chave: str = Field(min_length=1, max_length=200)
    papel: PapelDaChavePix
    modelo_id: UUID | None = None
    vendedor_id: UUID | None = None
    titular: str | None = Field(default=None, max_length=200)
    descricao: str | None = Field(default=None, max_length=500)
    padrao: bool = False
    """`true` marca esta como a padrao da casa e desmarca a anterior — so vale com `papel=casa`."""

    @model_validator(mode="after")
    def _validar(self) -> "ChavePixCriar":
        validar_papel_x_dono_da_chave(self.papel, self.modelo_id, self.vendedor_id)
        if self.padrao and self.papel != "casa":
            raise ValueError("So chave da casa pode ser a padrao.")
        return self


class ChavePixPatch(BaseModel):
    """Patch parcial (`exclude_unset`): so o que veio e tocado.

    ⚠️ Trocar o `papel` costuma exigir trocar o dono na mesma chamada — mandar `papel=modelo`
    sozinho, numa chave que era `casa`, e recusado aqui com a mensagem certa, e nao com o erro de
    constraint do banco.

    ⚠️ `ativo=false` e a inativacao, nunca exclusao: chave que saiu de uso continua explicando os
    comprovantes antigos que apontam para ela. Nao existe DELETE nesta aba. Inativar a chave
    `padrao` limpa a padrao junto (a rota faz os dois na mesma transacao) — e perder a padrao,
    alguem precisa escolher outra.
    """

    chave: str | None = Field(default=None, min_length=1, max_length=200)
    papel: PapelDaChavePix | None = None
    modelo_id: UUID | None = None
    vendedor_id: UUID | None = None
    titular: str | None = Field(default=None, max_length=200)
    descricao: str | None = Field(default=None, max_length=500)
    padrao: bool | None = None
    ativo: bool | None = None

    @model_validator(mode="after")
    def _validar(self) -> "ChavePixPatch":
        if self.papel is not None:
            validar_papel_x_dono_da_chave(self.papel, self.modelo_id, self.vendedor_id)
        if self.padrao and self.papel is not None and self.papel != "casa":
            raise ValueError("So chave da casa pode ser a padrao.")
        return self


# ------------- Sugestões de cadastro: a chave desconhecida recorrente (ticket 05) --------------


class ModeloQueMandou(BaseModel):
    """Em cujo grupo o comprovante apareceu — o "sempre recebendo da Yasmin" da sugestão."""

    id: UUID
    nome: str


class SugestaoDeChavePixResponse(BaseModel):
    """Uma chave que os comprovantes já mostraram mais de uma vez e que o cadastro não explica.

    Não é um cadastro pendente nem uma chave "quase cadastrada": é uma PERGUNTA derivada dos
    comprovantes que já existem. Nada aqui vira linha de `chaves_pix_conhecidas` sem o gestor
    responder — classificar é o mesmo `POST /chaves-pix` de sempre (ADR-0049 §5).

    Some da lista no instante em que a chave é cadastrada, porque a fila é uma consulta, não uma
    tabela: cadastrar É o gesto que tira a linha daqui.
    """

    chave: str
    """A grafia mais recente lida pelo OCR — é com ela que o gestor confere a tela do banco."""
    chave_normalizada: str
    pergunta: str
    """A frase pronta: "Apareceu 4 vezes em 3 semanas, sempre recebendo da Yasmin — de quem é?"."""
    vezes: int
    primeiro_em: date
    ultimo_em: date
    valor_total_brl: float
    """Quanto dinheiro já foi para este destino na janela — o tamanho da dúvida, em reais.

    `float` com o sufixo `_brl`, como o resto do painel: é número de leitura, para dimensionar a
    dúvida, e nunca entra em conta de razão."""
    titulares: list[str]
    """Os nomes que o OCR leu no destino. Viram o `titular` sugerido no formulário."""
    modelos: list[ModeloQueMandou]
    modelo_id_sugerido: UUID | None
    """Preenchido só quando UMA modelo mandou tudo — o palpite que o botão "de quem é?"
    pré-seleciona no papel `modelo`. É palpite, e o gestor troca; com duas modelos ele é `null`,
    porque a mesma chave recebendo de várias é outra conversa."""


class SugestoesDeChavePixListaResponse(BaseModel):
    items: list[SugestaoDeChavePixResponse]
