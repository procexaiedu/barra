export type IaPausadaMotivo = 'pix_em_revisao' | 'modelo_em_atendimento' | 'handoff_ia'
export type EstadoBloqueio = 'bloqueado' | 'em_atendimento' | 'concluido' | 'cancelado'
export type OrigemBloqueio = 'ia' | 'painel_fernando' | 'manual'

export interface ModeloAtiva {
  id: string
  nome: string
  evolution_instance_id: string | null
}

export interface CardDestaque {
  atendimento_id: string
  numero_curto: number
  cliente_nome: string | null
  cliente_telefone_formatado: string
  ia_pausada_motivo: IaPausadaMotivo
  motivo_escalada: string | null
  proxima_acao_esperada: string | null
  responsavel_atual: 'IA' | 'Fernando' | 'modelo'
  ia_pausada_em: string
  previsao_termino: string | null
  expirado: boolean
  modelo_nome: string
}

export interface MetricasDia {
  abertos: number
  fechamentos_hoje: number
  perdas_hoje: number
  valor_bruto_hoje_brl: number
  pix_em_revisao_pendentes: number
}

export interface LinhaAgenda {
  id: string
  inicio: string
  fim: string
  estado: EstadoBloqueio
  origem: OrigemBloqueio
  cliente_nome: string | null
  observacao: string | null
  atendimento_id: string | null
  modelo_nome: string
}

export interface PainelResumo {
  modelos_ativas: ModeloAtiva[]
  cards_destaque: CardDestaque[]
  metricas_dia: MetricasDia
  agenda_dia: LinhaAgenda[]
  servidor_em: string
}
