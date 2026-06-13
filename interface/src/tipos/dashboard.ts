import type { MotivoPerda } from "./atendimentos"
import type { PresetPeriodo } from "./filtros"

/** @deprecated use `PresetPeriodo` de `./filtros` — alias mantido p/ compatibilidade. */
export type FiltroPeriodo = PresetPeriodo

export const TIPOS_ESCALADA = [
  "pix_validado",
  "pix_duvidoso",
  "foto_portaria",
  "aviso_saida",
  "fora_de_oferta",
  "comportamento_atipico",
  "indisponibilidade",
  "cliente_busca",
  "video_chamada",
  "outro",
] as const

export type TipoEscalada = (typeof TIPOS_ESCALADA)[number]

export interface FiltroAplicado {
  periodo: FiltroPeriodo
  de: string
  ate: string
  modelo_ids: string[]
}

export interface JanelaComparacao {
  de: string
  ate: string
}

export interface ModeloResumoDashboard {
  id: string
  nome: string
}

export interface KpisFechamentos {
  contagem: number
  valor_bruto_brl: number
  valor_medio_brl: number
  valor_liquido_brl: number
  valor_repasse_modelo_brl: number
  valor_sem_repasse_definido_brl: number
  contagem_sem_snapshot: number
  n_referencia?: number
}

export interface FinanceiroBloco {
  valor_bruto_brl: number
  valor_liquido_brl: number
  valor_repasse_modelo_brl: number
  valor_sem_repasse_definido_brl: number
  fechamentos_total: number
  fechamentos_sem_snapshot: number
}

export interface KpisPeriodo {
  taxa_conversao_pct: number | null
  n_decididos?: number
  volume_periodo?: number
  fechamentos: KpisFechamentos
  perdas: { contagem: number; n_referencia?: number }
  escaladas: { contagem: number; n_referencia?: number }
}

// Etapas de progressão do funil (Perdido não é etapa — vira saída lateral).
// O id casa com o param ?estado= aceito por /atendimentos.
export type EtapaFunilId = "Qualificando" | "Aguardando" | "Em_execucao" | "Fechado"

export interface FunilEtapa {
  id: EtapaFunilId
  coorte: number // quantos atendimentos chegaram pelo menos até esta etapa
  perdas: number // Perdidos cuja etapa de origem é esta (saída lateral)
}

export interface FunilCoorte {
  topo: number // total de atendimentos que entraram no período (= coorte de Qualificando)
  etapas: FunilEtapa[]
  perdidos_total: number
}

export interface PerdaPorMotivoLinha {
  motivo: MotivoPerda
  contagem: number
}

export interface MotivoEscaladaLinha {
  motivo: string
  tipo?: TipoEscalada
  contagem: number
}

export interface BreakdownModelo {
  modelo_id: string
  nome: string
  contagem: number
}

export interface MotivoEscaladaPorTipo {
  tipo: TipoEscalada
  rotulo: string
  contagem: number
  por_modelo: BreakdownModelo[]
}

export interface MotivosEscalada {
  por_tipo?: MotivoEscaladaPorTipo[]
  top5: MotivoEscaladaLinha[]
  outros_total: number
  total: number
}

export interface ProfissionalRanking {
  modelo: ModeloResumoDashboard
  volume: number
  fechamentos: number
  perdas?: number
  valor_bruto_brl: number
  valor_liquido_brl: number
  valor_repasse_modelo_brl: number
  taxa_conversao_pct: number | null
  n_referencia?: number
}

export interface DashboardResumo {
  filtro_aplicado: FiltroAplicado
  janela_comparacao: JanelaComparacao | null
  pix_em_revisao_pendentes_total: number
  kpis_periodo: KpisPeriodo
  kpis_periodo_anterior: KpisPeriodo | null
  financeiro: FinanceiroBloco
  financeiro_periodo_anterior: FinanceiroBloco | null
  funil: FunilCoorte
  perdas_por_motivo: PerdaPorMotivoLinha[]
  motivos_escalada: MotivosEscalada
  profissionais: ProfissionalRanking[]
  servidor_em: string
}

export interface EscaladaCompletaLinha {
  motivo: string
  tipo?: TipoEscalada
  rotulo?: string
  observacao?: string | null
  modelo_nome?: string
  contagem: number
}

export interface DashboardEscaladasResponse {
  filtro_aplicado: FiltroAplicado
  motivos: EscaladaCompletaLinha[]
}

export type SerieMetrica = "conversao" | "fechamentos" | "perdas" | "escaladas" | "liquido" | "bruto"
export type SerieUnidade = "dia" | "semana"

export interface SerieTemporalPonto {
  data: string
  valor: number | null
  n_referencia?: number
}

export interface SerieResposta {
  metrica: SerieMetrica
  unidade: SerieUnidade
  n: number
  modelo_ids: string[]
  pontos: SerieTemporalPonto[]
}
