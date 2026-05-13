export type MotivoPerda =
  | "preco"
  | "sumiu"
  | "risco"
  | "indisponibilidade"
  | "fora_de_area"
  | "outro"

export type DirecaoMensagem = "cliente" | "ia" | "modelo_manual"

export type EstadoAtendimento =
  | "Novo"
  | "Triagem"
  | "Qualificado"
  | "Aguardando_confirmacao"
  | "Confirmado"
  | "Em_execucao"
  | "Fechado"
  | "Perdido"

export type TipoAtendimento = "interno" | "externo"
export type Urgencia = "imediato" | "agendado" | "indefinido" | "estimado"

export type FiltroRecorrencia = "todas" | "novas" | "recorrentes"
export type FiltroPeriodo = "todos" | "7d" | "30d" | "90d"
export type FiltroMotivoPerda = "todos" | MotivoPerda
export type FiltroModelo = "todas" | string
export type FiltroOrdem = "recente" | "inatividade"

export interface ClienteResumo {
  id: string
  nome: string | null
  telefone: string
}

export interface Cliente {
  id: string
  nome: string | null
  telefone: string
  arquivado_em: string | null
  created_at: string
  updated_at: string
}

export interface ClienteListItem {
  id: string
  nome: string | null
  telefone_mascarado: string | null
  primeiro_contato_modelo_id: string | null
  arquivado_em: string | null
  created_at: string
  updated_at: string
}

export interface ClientesListaResponse {
  items: ClienteListItem[]
  next_cursor: string | null
}

export interface CriarClienteRequest {
  nome?: string | null
  telefone: string
}

export interface EditarClienteRequest {
  nome?: string | null
  telefone?: string
}

export interface ModeloResumo {
  id: string
  nome: string
}

export interface UltimoAtendimentoResumo {
  numero_curto: number
  estado: EstadoAtendimento
  created_at: string
  valor_final: number | null
  motivo_perda: MotivoPerda | null
}

export interface ConversaListaItem {
  id: string
  cliente: ClienteResumo
  modelo: ModeloResumo
  recorrente: boolean
  ultima_mensagem_em: string | null
  ultima_mensagem_direcao: DirecaoMensagem | null
  ultimo_motivo_perda: MotivoPerda | null
  ultimo_atendimento: UltimoAtendimentoResumo | null
  tem_atendimento_aberto: boolean
  ultimo_fechamento_em: string | null
  created_at: string
}

export interface ConversasListaResponse {
  items: ConversaListaItem[]
  next_cursor: string | null
}

export type FormaPagamento = "pix" | "dinheiro" | "outro"

export interface ClienteDetalhe {
  id: string
  nome: string | null
  telefone: string
  primeiro_contato_modelo_nome: string | null
  created_at: string
  arquivado_em?: string | null
  modelo_preferida: ModeloResumo | null
  tipo_atendimento_mais_frequente: "interno" | "externo" | null
  programa_preferido: { id: string; nome: string } | null
  duracao_preferida: { id: string; nome: string } | null
  forma_pagamento_preferida: FormaPagamento | null
}

export interface AtendimentoAberto {
  id: string
  numero_curto: number
  estado: EstadoAtendimento
  tipo_atendimento: TipoAtendimento | null
  urgencia: Urgencia | null
  valor_acordado: number | null
  proxima_acao_esperada: string | null
  forma_pagamento: FormaPagamento | null
  programa: { id: string; nome: string } | null
  duracao: { id: string; nome: string } | null
}

export interface AtendimentoHistoricoItem {
  id: string
  numero_curto: number
  estado: "Fechado" | "Perdido"
  valor_final: number | null
  motivo_perda: MotivoPerda | null
  motivo_perda_obs: string | null
  created_at: string
  tipo_atendimento: TipoAtendimento | null
  forma_pagamento: FormaPagamento | null
  programa: { id: string; nome: string } | null
  duracao: { id: string; nome: string } | null
}

export interface ConversaResumo {
  id: string
  recorrente: boolean
  observacoes_internas: string | null
  ultimo_motivo_perda: MotivoPerda | null
  ultima_mensagem_em: string | null
  ultima_mensagem_direcao: DirecaoMensagem | null
  created_at: string
}

export interface ConversaDetalheResponse {
  conversa: ConversaResumo
  cliente: ClienteDetalhe
  modelo: ModeloResumo
  atendimento_aberto: AtendimentoAberto | null
  historico_atendimentos: AtendimentoHistoricoItem[]
}

export interface FiltrosClientes {
  busca: string
  recorrencia: FiltroRecorrencia
  motivoPerda: FiltroMotivoPerda
  periodo: FiltroPeriodo
  modeloId: FiltroModelo
  ordenarPor: FiltroOrdem
}
