/**
 * As duas ações do painel que MOVEM DINHEIRO (ticket 05): o vale adiantado e o fechamento da
 * temporada com o pagamento feito à modelo.
 *
 * Espelha os DTOs de `api/src/barra/dominio/financeiro/schemas.py` — divergir aqui não quebra o
 * build, quebra a tela em produção, então cada nome abaixo é o nome literal do backend.
 *
 * Ficam colocados em `_acoes/` (e não em `src/tipos/`) porque só a tela de Temporadas os usa;
 * `src/tipos/razao.ts` continua sendo o espelho da LEITURA, compartilhado com a ficha da modelo.
 *
 * ⚠️ Nenhum destes tipos carrega saldo GRAVADO (ADR-0045 §7): `FechamentoDaTemporada` é apurado a
 * cada leitura. Um comprovante que chegar depois de a temporada estar paga muda
 * `saldo.falta_pagar_brl` na próxima resposta — não existe reabertura porque nunca houve
 * congelamento.
 */

import type {
  EstadoDaTemporada,
  PagamentoDaModeloLinha,
  SaldoDoRazao,
  SinalizacaoDoExtrato,
} from "@/tipos/razao"

export type TipoDoLancamentoManual = "vale" | "ajuste"
export type SentidoDoLancamentoManual = "debito" | "credito"

/** `painel` = o gestor digitou (tem `created_by`); `grupo` = o agente leu a fala, com recibo. */
export type OrigemDoLancamentoManual = "painel" | "grupo"

/** As formas com que a CASA paga a modelo — não confundir com as cinco formas da venda. */
export const FORMAS_DO_PAGAMENTO = ["pix", "dinheiro", "outro"] as const
export type FormaDoPagamento = (typeof FORMAS_DO_PAGAMENTO)[number]

export interface TemporadaResponse {
  id: string
  modelo_id: string
  modelo_nome: string
  cidade: string
  data_inicio: string
  data_fim: string
  estado: EstadoDaTemporada
  observacao: string | null
  fechada_em: string | null
}

export interface LancamentoManualResponse {
  id: string
  modelo_id: string
  tipo: TipoDoLancamentoManual
  sentido: SentidoDoLancamentoManual
  valor_brl: number
  data: string
  descricao: string | null
  origem: OrigemDoLancamentoManual
  temporada_id: string | null
  anulado_em: string | null
}

export interface FechamentoDaTemporada {
  temporada: TemporadaResponse
  saldo: SaldoDoRazao
  /** `falta_pagar_brl` sem o lado negativo: quanto a casa ainda deve. */
  sugestao_de_pagamento_brl: number
  vendas: number
  vendido_brl: number
  pendencias: SinalizacaoDoExtrato[]
  divergencias: SinalizacaoDoExtrato[]
  pagamentos: PagamentoDaModeloLinha[]
  vales: LancamentoManualResponse[]
}

/**
 * Aceita "1.234,56" e "1234.56" — o gestor digita das duas formas. `null` = não é número.
 *
 * A vírgula é o desempate: com ela, o ponto é separador de milhar ("1.234,56"); sem ela, o ponto
 * é o decimal ("1234.56"). Limpar o ponto sempre transformaria 1234.56 em 123456 — um erro de
 * cem vezes, calado, num campo de dinheiro.
 */
export function lerValor(bruto: string): number | null {
  const texto = bruto.trim()
  if (texto === "") return null
  const limpo = texto.includes(",") ? texto.replace(/\./g, "").replace(",", ".") : texto
  const n = Number(limpo)
  return Number.isFinite(n) ? n : null
}

export const hojeISO = () => new Date().toISOString().slice(0, 10)
