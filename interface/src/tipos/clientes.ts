export type MotivoPerda =
  | "preco"
  | "sumiu"
  | "risco"
  | "indisponibilidade"
  | "fora_de_area"
  | "outro"

/** Perfil físico (eixo único). Slug ASCII; rótulo acentuado em lib/perfilFisico. ADR 0006. */
export type PerfilFisico =
  | "loira"
  | "morena"
  | "ruiva"
  | "negra"
  | "asiatica"
  | "outra"

/** Preferência física CALCULADA do histórico (cross-modelo, painel-only). */
export interface PerfilCalculado {
  breakdown: { tipo: PerfilFisico; qtd: number }[]
  nao_classificadas: number
}

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

export type FiltroPeriodo = "todos" | "7d" | "30d" | "90d"
export type FiltroModelo = "todas" | string

export interface Cliente {
  id: string
  nome: string | null
  telefone: string
  perfis_preferidos: PerfilFisico[]
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

/** Item da tela "Clientes": cliente + agregados por cliente (todas as modelos). */
export interface ClienteListaItem extends ClienteListItem {
  total_atendimentos: number
  valor_total: number
  ultima_atividade: string | null
  modelos_distintas: number
  modelo_predominante_nome: string | null
  recorrente: boolean
}

export interface ClientesAgregadosResponse {
  items: ClienteListaItem[]
  next_cursor: string | null
}

/** Ponto do Mapa de clientes (ADR 0008): 1 por cliente, no externo mais recente com geo. */
export interface MapaClientePonto {
  cliente_id: string
  nome: string | null
  latitude: number
  longitude: number
  bairro: string | null
  endereco_formatado: string | null
  total_atendimentos: number
  valor_total: number
  /** Perfil físico DECLARADO (ADR 0006). Array vazio = sem preferência declarada.
   *  Nunca o breakdown calculado — esse é cross-modelo e fica fora do mapa (painel-only por par). */
  perfis: PerfilFisico[]
}

export interface MapaClientesResponse {
  pontos: MapaClientePonto[]
  /** Clientes que batem nos filtros mas não têm externo geocodificado — não viram pin. */
  total_sem_localizacao: number
}

/** Conversa (par cliente, modelo) listada no detalhe do cliente. */
export interface ClienteConversaResumo {
  id: string
  modelo_id: string
  modelo_nome: string
  recorrente: boolean
  ultimo_motivo_perda: MotivoPerda | null
  ultima_mensagem_em: string | null
  observacoes_internas: string | null
}

export interface ClienteDetalheResponse {
  cliente: {
    id: string
    nome: string | null
    telefone_mascarado: string | null
    perfis_preferidos: PerfilFisico[]
    primeiro_contato_modelo_id: string | null
    arquivado_em: string | null
    created_at: string
    updated_at: string
  }
  conversas: ClienteConversaResumo[]
}

export interface CriarClienteRequest {
  nome?: string | null
  telefone: string
  perfis_preferidos?: PerfilFisico[]
}

export interface EditarClienteRequest {
  nome?: string | null
  telefone?: string
  perfis_preferidos?: PerfilFisico[]
}

export interface ModeloResumo {
  id: string
  nome: string
}


export type FormaPagamento = "pix" | "dinheiro" | "outro" | "cartao"

export interface ClienteDetalhe {
  id: string
  nome: string | null
  telefone: string
  primeiro_contato_modelo_nome: string | null
  created_at: string
  arquivado_em?: string | null
  perfis_preferidos: PerfilFisico[]
  perfil_calculado: PerfilCalculado
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
  periodo: FiltroPeriodo
  modeloId: FiltroModelo
  perfis: PerfilFisico[]
}
