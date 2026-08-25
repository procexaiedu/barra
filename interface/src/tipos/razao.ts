/**
 * O razão da modelo, a Temporada e a conferência por forma (ticket 04).
 *
 * Espelha os DTOs de `api/src/barra/dominio/financeiro/schemas.py`. Divergir aqui não quebra o
 * build — quebra a tela em produção — então cada nome abaixo é o nome literal do backend.
 *
 * ⚠️ Nenhum destes tipos carrega comissão de telefonista (ADR-0048): são duas contas de pessoas
 * diferentes, e a modelo lê o extrato dela junto com o gestor.
 */

export type EstadoDaTemporada = "aberta" | "fechada" | "cancelada"

export type TipoDaLinhaDoExtrato =
  | "venda"
  | "comissao"
  | "transferencia"
  | "cobranca"
  | "vale"
  | "ajuste"
  | "deslocamento"

export type OrigemDaLinhaDoExtrato =
  | "venda_registrada"
  | "comprovante_do_grupo"
  | "cobranca_da_agencia"
  | "razao_lancamento_manual"
  | "deslocamento_da_venda"

/**
 * `saldo_brl` positivo = a casa deve a ela; negativo = ela deve à casa.
 *
 * `pago_brl` NÃO está dentro de `saldo_brl`: a Temporada não congela cálculo (ADR-0045 §7), o
 * saldo segue derivado dos fatos e o que já foi pago fica ao lado — `falta_pagar_brl` é a
 * diferença, e é ela que responde "falta pagar quanto?".
 */
export interface SaldoDoRazao {
  debitos_brl: number
  creditos_brl: number
  saldo_brl: number
  a_casa_deve_brl: number
  ela_deve_brl: number
  pago_brl: number
  falta_pagar_brl: number
}

export interface ConferenciaFormaLinha {
  /** pix | dinheiro | debito | credito | link | sem_forma — `string` porque dado antigo fora do
   *  vocabulário tem que APARECER na conferência, não sumir dela. */
  forma: string
  vendas: number
  valor_brl: number
}

export interface ConferenciaPorFormaResponse {
  de: string | null
  ate: string | null
  formas: ConferenciaFormaLinha[]
  vendas: number
  vendido_brl: number
}

export interface LinhaDoExtrato {
  tipo: TipoDaLinhaDoExtrato
  origem: OrigemDaLinhaDoExtrato
  origem_id: string | null
  data: string
  descricao: string | null
  debito_brl: number
  credito_brl: number
}

export interface PagamentoDaModeloLinha {
  id: string
  data: string
  valor_brl: number
  forma_pagamento: string
  observacao: string | null
  temporada_id: string | null
}

export interface SinalizacaoDoExtrato {
  tipo: string
  quantidade: number
  valor_brl: number
}

export interface TemporadaLinha {
  id: string
  modelo_id: string
  modelo_nome: string
  cidade: string
  data_inicio: string
  data_fim: string
  estado: EstadoDaTemporada
  observacao: string | null
  fechada_em: string | null
  vendas: number
  vendido_brl: number
  saldo: SaldoDoRazao
  pendencias: number
}

export interface TemporadasListaResponse {
  items: TemporadaLinha[]
  total_a_casa_deve_brl: number
  total_ela_deve_brl: number
  total_falta_pagar_brl: number
}

export interface ExtratoDaModeloResponse {
  modelo_id: string
  modelo_nome: string
  percentual_repasse: number | null
  de: string | null
  ate: string | null
  temporada_id: string | null
  temporada_cidade: string | null
  temporada_estado: EstadoDaTemporada | null
  saldo: SaldoDoRazao
  conferencia: ConferenciaPorFormaResponse
  linhas: LinhaDoExtrato[]
  pagamentos: PagamentoDaModeloLinha[]
  pendencias: SinalizacaoDoExtrato[]
  divergencias: SinalizacaoDoExtrato[]
}

/** As cinco formas que a operação usa de fato (ADR-0046 §4) + a venda sem forma dita. */
export const ORDEM_DAS_FORMAS = ["pix", "dinheiro", "debito", "credito", "link", "sem_forma"] as const

export const ROTULO_DA_FORMA: Record<string, string> = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  debito: "Débito",
  credito: "Crédito",
  link: "Link",
  sem_forma: "Sem forma",
}

export const ROTULO_DA_LINHA: Record<TipoDaLinhaDoExtrato, string> = {
  venda: "Venda no bolso dela",
  comissao: "Comissão",
  transferencia: "Transferência para a casa",
  cobranca: "Cobrança da agência",
  vale: "Vale adiantado",
  ajuste: "Ajuste manual",
  deslocamento: "Deslocamento",
}

export const ROTULO_DA_ORIGEM: Record<OrigemDaLinhaDoExtrato, string> = {
  venda_registrada: "Venda registrada",
  comprovante_do_grupo: "Comprovante do grupo",
  cobranca_da_agencia: "Cobrança da agência",
  razao_lancamento_manual: "Lançamento do painel",
  deslocamento_da_venda: "Deslocamento da venda",
}

/** Pendência é fila, não erro — `bolso = 'nao_dito'` é estado legítimo (ADR-0047 §3). */
export const ROTULO_DA_PENDENCIA: Record<string, string> = {
  venda_sem_forma_de_pagamento: "venda sem forma de pagamento",
  venda_com_bolso_nao_dito: "venda sem o bolso dito (contada como dela)",
  cobranca_em_aberto: "cobrança da agência em aberto",
  comprovante_retido: "comprovante retido (não classificado ou ilegível)",
}

export const ROTULO_DA_DIVERGENCIA: Record<string, string> = {
  venda_sem_snapshot_de_comissao: "venda sem percentual congelado — comissão não creditada",
  comprovante_com_sobra: "comprovante com sobra a favor dela",
}
