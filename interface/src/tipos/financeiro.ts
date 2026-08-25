// Tipos do Módulo Financeiro (ADR 0011). Espelham os schemas Pydantic em
// `api/src/barra/dominio/financeiro/schemas.py`.

import type { FiltroAplicado, JanelaComparacao, ReceitaDasDuasFontes } from "./dashboard"

export type { ReceitaDasDuasFontes }

export type FormaPagamentoRepasse = "pix" | "dinheiro" | "outro"
export type FormaPagamentoReceita = "pix" | "dinheiro" | "cartao" | "outro"

// ---------- Resumo ----------

export interface FinanceiroResumo {
  valor_bruto_brl: number
  valor_liquido_brl: number
  valor_repasse_calculado_brl: number
  valor_sem_repasse_definido_brl: number
  valor_repasse_pago_brl: number
  valor_saldo_repasse_brl: number
  fechamentos_total: number
  fechamentos_sem_snapshot: number
}

/** Fechados sem data (sem evento `fechado_registrado`) — fora do recorte por período. */
export interface ImportadosSemData {
  contagem: number
  valor_bruto_brl: number
}

export interface FinanceiroResumoResponse {
  filtro_aplicado: FiltroAplicado
  janela_comparacao: JanelaComparacao | null
  resumo: FinanceiroResumo
  resumo_anterior: FinanceiroResumo | null
  importados_sem_data: ImportadosSemData
  receita_das_duas_fontes: ReceitaDasDuasFontes
  receita_das_duas_fontes_anterior: ReceitaDasDuasFontes | null
}

// ---------- Vendas registradas (ADR-0043 / spec 0005) ----------

/**
 * As CINCO formas da Venda registrada (ADR-0046 §4): "cartão" deixou de ser uma forma só e virou
 * débito, crédito e link — cada uma concilia no seu extrato. Espelha
 * `FormaPagamentoVendaRegistrada` / `FORMAS_DA_VENDA_REGISTRADA` do backend e o CHECK de
 * `vendas_registradas.forma_pagamento`. Ficou em `"pix" | "dinheiro"` depois da v2, enquanto o
 * `ConferenciaPorForma` já mostrava as cinco.
 */
export type FormaPagamentoVendaRegistrada = "pix" | "dinheiro" | "debito" | "credito" | "link"
export type TipoDePendenciaVenda = "forma_pagamento" | "comprovante"
export type EstadoDeConciliacaoVenda =
  | "anulada"
  | "aguardando_forma"
  | "em_especie"
  | "aguardando_comprovante"
  | "conciliada"
export type TipoDeDivergenciaFechamento =
  | "comprovante_sem_par"
  | "credito_da_modelo"
  | "pix_sem_venda_em_pix"
  | "venda_comprovada_a_menor"

/** Uma venda anunciada no Grupo financeiro. Somente leitura: corrige-se no grupo. */
export interface VendaRegistradaLinha {
  id: string
  modelo_id: string
  modelo_nome: string
  data: string // AAAA-MM-DD
  valor: number
  cliente_nome: string | null // texto livre: nunca vira linha em `clientes`
  local_atendimento: string | null
  duracao_minutos: number | null
  forma_pagamento: FormaPagamentoVendaRegistrada | null
  conciliacao: EstadoDeConciliacaoVenda
  pendencias: TipoDePendenciaVenda[]
  comprovante_id: string | null
  chave_pix_desconhecida: boolean
  chave_pix_destino: string | null
  anulada_em: string | null
  mensagem_id: string
}

/** Divergência do Fechamento — da MODELO (conferência), não de uma venda. */
export interface DivergenciaDoFechamento {
  modelo_id: string
  modelo_nome: string
  tipo: TipoDeDivergenciaFechamento
  valor: number
  data: string | null
  comprovante_id: string | null
}

export interface VendasRegistradasListaResponse {
  filtro_aplicado: FiltroAplicado
  items: VendaRegistradaLinha[]
  next_cursor: string | null
  divergencias: DivergenciaDoFechamento[]
}

// ---------- Receitas ----------

export interface ReceitaLinha {
  atendimento_id: string
  numero_curto: number
  fechado_em: string
  modelo_id: string
  modelo_nome: string
  cliente_id: string
  cliente_nome: string
  forma_pagamento: FormaPagamentoReceita | null
  valor_bruto: number
  percentual_repasse_snapshot: number | null
  valor_repasse_calculado: number
}

export interface ReceitasListaResponse {
  filtro_aplicado: FiltroAplicado
  items: ReceitaLinha[]
  next_cursor: string | null
}

// ---------- Inspector lateral (contexto da receita) ----------

export interface ContextoCliente {
  cliente_id: string
  nome: string
  total_atendimentos: number
  total_fechados: number
  valor_total_brl: number
  ultima_atividade_iso: string | null
  modelos_distintas: number
}

export interface ContextoModeloDia {
  dia: string
  bruto: number
}

export interface ContextoModelo {
  modelo_id: string
  nome: string
  fechamentos_periodo: number
  valor_bruto_periodo: number
  valor_repasse_periodo: number
  serie_30d: ContextoModeloDia[]
}

export interface ReceitaContextoResponse {
  atendimento_id: string
  cliente: ContextoCliente
  modelo: ContextoModelo
}

// ---------- Repasses ----------

export interface SaldoModelo {
  modelo_id: string
  modelo_nome: string
  fechamentos_total: number
  valor_bruto: number
  valor_repasse_calculado: number
  valor_repasse_pago: number
  saldo: number
  fechamentos_sem_snapshot: number
  valor_sem_snapshot: number
}

export interface RepassesPorModeloResponse {
  filtro_aplicado: FiltroAplicado
  items: SaldoModelo[]
}

export interface RepassePagoResponse {
  id: string
  modelo_id: string
  modelo_nome: string | null
  data_pagamento: string
  valor: number
  forma_pagamento: FormaPagamentoRepasse
  observacao: string | null
  comprovante_object_key: string | null
  created_at: string
  updated_at: string
}

export interface RepassesPagamentosListaResponse {
  filtro_aplicado: FiltroAplicado
  items: RepassePagoResponse[]
  next_cursor: string | null
}

export interface RepassePagoCriarInput {
  modelo_id: string
  data_pagamento: string
  valor: number
  forma_pagamento: FormaPagamentoRepasse
  observacao?: string | null
  comprovante_object_key?: string | null
}

// ---------- Preencher retroativo ----------

export interface AtendimentoSemSnapshotLinha {
  atendimento_id: string
  numero_curto: number
  fechado_em: string
  cliente_nome: string
  valor_bruto: number
}

export interface AtendimentosSemSnapshotResponse {
  modelo_id: string
  items: AtendimentoSemSnapshotLinha[]
}

export interface PreencherRepasseRetroativoInput {
  atendimento_ids: string[]
  percentual: number
}

// ---------- Série / visão geral analítica ----------

export interface FinanceiroSerieDia {
  dia: string // AAAA-MM-DD (BRT)
  bruto: number
  repasse_calculado: number
  liquido: number
  fechamentos: number
}

export interface FinanceiroMixForma {
  forma_pagamento: string // pix | dinheiro | cartao | outro | indefinido
  valor_bruto: number
  fechamentos: number
}

export interface FinanceiroTopModelo {
  modelo_id: string
  modelo_nome: string
  bruto: number
  liquido: number
  repasse_calculado: number
  fechamentos: number
}

export interface FinanceiroSerieResponse {
  filtro_aplicado: FiltroAplicado
  serie_diaria: FinanceiroSerieDia[]
  mix_forma_pagamento: FinanceiroMixForma[]
  top_modelos: FinanceiroTopModelo[]
}
