// Tipos do Módulo Financeiro (ADR 0011). Espelham os schemas Pydantic em
// `api/src/barra/dominio/financeiro/schemas.py`.

import type { FiltroAplicado, JanelaComparacao } from "./dashboard"

export type CategoriaDespesa =
  | "anuncios"
  | "software"
  | "infraestrutura"
  | "juridico"
  | "taxas"
  | "deslocamento"
  | "pessoal"
  | "outro"

export const CATEGORIAS_DESPESA: CategoriaDespesa[] = [
  "anuncios",
  "software",
  "infraestrutura",
  "juridico",
  "taxas",
  "deslocamento",
  "pessoal",
  "outro",
]

export const ROTULO_CATEGORIA: Record<CategoriaDespesa, string> = {
  anuncios: "Anúncios",
  software: "Software",
  infraestrutura: "Infraestrutura",
  juridico: "Jurídico",
  taxas: "Taxas",
  deslocamento: "Deslocamento",
  pessoal: "Pessoal",
  outro: "Outro",
}

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
  valor_despesas_brl: number
  fechamentos_total: number
  fechamentos_sem_snapshot: number
}

export interface FinanceiroResumoResponse {
  filtro_aplicado: FiltroAplicado
  janela_comparacao: JanelaComparacao | null
  resumo: FinanceiroResumo
  resumo_anterior: FinanceiroResumo | null
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

// ---------- Despesas ----------

export type OrigemDespesa =
  | "pontual"
  | "recorrente_materializada"
  | "recorrente_projetada"

export interface DespesaLinha {
  id: string | null
  categoria: CategoriaDespesa
  valor: number
  data: string
  descricao: string | null
  recorrente_id: string | null
  competencia_mes: string | null
  origem: OrigemDespesa
  valor_template: number | null
}

export interface DespesasListaResponse {
  filtro_aplicado: FiltroAplicado
  items: DespesaLinha[]
  next_cursor: string | null
}

export interface DespesaCriarInput {
  categoria: CategoriaDespesa
  valor: number
  data: string
  descricao?: string | null
}

export interface DespesaPatchInput {
  categoria?: CategoriaDespesa
  valor?: number
  data?: string
  descricao?: string | null
}

// ---------- Recorrentes ----------

export interface DespesaRecorrente {
  id: string
  categoria: CategoriaDespesa
  valor: number
  descricao: string
  dia_do_mes: number
  ativo_desde: string
  inativo_em: string | null
  created_at: string
  updated_at: string
}

export interface DespesaRecorrenteCriarInput {
  categoria: CategoriaDespesa
  valor: number
  descricao: string
  dia_do_mes: number
  ativo_desde: string
}

export interface MaterializarRecorrenteInput {
  recorrente_id: string
  competencia_mes: string
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
