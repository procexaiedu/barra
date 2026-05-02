import type { EstadoAtendimento, MotivoPerda } from "./atendimentos"

export type FiltroPeriodo = "hoje" | "7d" | "30d" | "tudo" | "custom"

export interface FiltroAplicado {
  periodo: FiltroPeriodo
  de: string
  ate: string
  modelo_id: string | null
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
}

export interface KpisPeriodo {
  taxa_conversao_pct: number | null
  fechamentos: KpisFechamentos
  perdas: { contagem: number }
  escaladas: { contagem: number }
}

export interface FunilEstadoLinha {
  estado: EstadoAtendimento
  contagem: number
}

export interface PerdaPorMotivoLinha {
  motivo: MotivoPerda
  contagem: number
}

export interface MotivoEscaladaLinha {
  motivo: string
  contagem: number
}

export interface MotivosEscalada {
  top5: MotivoEscaladaLinha[]
  outros_total: number
  total: number
}

export interface ProfissionalRanking {
  modelo: ModeloResumoDashboard
  volume: number
  fechamentos: number
  valor_bruto_brl: number
  taxa_conversao_pct: number | null
}

export interface DashboardResumo {
  filtro_aplicado: FiltroAplicado
  janela_comparacao: JanelaComparacao | null
  pix_em_revisao_pendentes_total: number
  kpis_periodo: KpisPeriodo
  kpis_periodo_anterior: KpisPeriodo | null
  funil_estados: FunilEstadoLinha[]
  perdas_por_motivo: PerdaPorMotivoLinha[]
  motivos_escalada: MotivosEscalada
  profissionais: ProfissionalRanking[]
  servidor_em: string
}

export interface EscaladaCompletaLinha {
  motivo: string
  contagem: number
}

export interface DashboardEscaladasResponse {
  filtro_aplicado: FiltroAplicado
  motivos: EscaladaCompletaLinha[]
}
