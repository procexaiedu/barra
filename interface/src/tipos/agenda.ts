export type EstadoBloqueio = "bloqueado" | "em_atendimento" | "concluido" | "cancelado"
export type OrigemBloqueio = "ia" | "painel_fernando" | "manual"
export type VisaoAgenda = "dia" | "semana" | "mes"

export interface ModeloAgenda {
  id: string
  nome: string
}

export interface AtendimentoAgendaResumo {
  id: string
  numero_curto: number
  cliente_nome: string | null
  cliente_telefone_formatado: string
  estado: string
  tipo_atendimento: string | null
  valor_acordado: string | null
  endereco: string | null
  bairro: string | null
  data_desejada: string | null
  horario_desejado: string | null
  programa_principal_nome: string | null
}

export interface BloqueioAgenda {
  id: string
  modelo_id: string
  modelo_nome?: string
  inicio: string
  fim: string
  estado: EstadoBloqueio
  origem: OrigemBloqueio
  observacao: string | null
  atendimento_id: string | null
  atendimento: AtendimentoAgendaResumo | null
}

export interface AgendaResponse {
  modelo: ModeloAgenda | null
  inicio: string
  fim: string
  bloqueios: BloqueioAgenda[]
}

export interface CriarBloqueioInput {
  modelo_id?: string
  inicio: string
  fim: string
  observacao: string | null
  atendimento_id?: string
  confirmar_fora_disponibilidade?: boolean
  confirmar_buffer?: boolean
}

export interface AtualizarBloqueioInput {
  inicio: string
  fim: string
  observacao: string | null
  atendimento_id?: string | null
  confirmar_fora_disponibilidade?: boolean
  confirmar_buffer?: boolean
}

export interface BloqueioFormState {
  modelo_id?: string
  data: string
  inicio: string
  fim: string
  observacao: string
  atendimento_id?: string
}
