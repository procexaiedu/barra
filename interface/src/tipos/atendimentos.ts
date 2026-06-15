import type { BloqueioAgenda } from "./agenda"
import type { PeriodoSelecionado } from "./filtros"

export type EstadoAtendimento =
  | "Novo"
  | "Triagem"
  | "Qualificado"
  | "Aguardando_confirmacao"
  | "Confirmado"
  | "Em_execucao"
  | "Fechado"
  | "Perdido"

export type TipoAtendimento = "interno" | "externo" | "remoto"
export type Urgencia = "imediato" | "agendado" | "indefinido" | "estimado"
export type IaPausadaMotivo = "pix_em_revisao" | "modelo_em_atendimento" | "handoff_ia"
export type ResponsavelAtual = "IA" | "Fernando" | "modelo"
export type MotivoPerda = "preco" | "sumiu" | "risco" | "indisponibilidade" | "fora_de_area" | "outro"
export type DirecaoMensagem = "cliente" | "ia" | "modelo_manual"
export type TipoMensagem = "texto" | "audio" | "imagem"
export type PixStatus = "nao_solicitado" | "aguardando" | "enviado" | "em_revisao" | "validado" | "invalido"

export interface AtendimentoListaItem {
  id: string
  numero_curto: number
  cliente: {
    id: string
    nome: string | null
    telefone: string
  }
  modelo: {
    id: string
    nome: string
  }
  estado: EstadoAtendimento
  tipo_atendimento: TipoAtendimento | null
  urgencia: Urgencia | null
  ia_pausada: boolean
  ia_pausada_motivo: IaPausadaMotivo | null
  responsavel_atual: ResponsavelAtual
  motivo_escalada: string | null
  proxima_acao_esperada: string | null
  sinais_qualificacao?: Record<string, unknown> | null
  valor_acordado: number | string | null
  valor_final: number | string | null
  updated_at: string
  programa_principal_nome: string | null
}

export interface AtendimentosListaResponse {
  items: AtendimentoListaItem[]
  next_cursor: string | null
}

export interface MensagemAtendimento {
  id: string
  direcao: DirecaoMensagem
  tipo: TipoMensagem
  conteudo: string
  media_object_key: string | null
  media_url?: string | null
  created_at: string
}

export interface EventoAtendimento {
  id: string
  tipo: string
  origem: string
  autor: string
  payload: Record<string, unknown>
  created_at: string
}

export interface ComprovantePixResumo {
  id: string
  valor_extraido: number | null
  chave_extraida: string | null
  titular_extraido: string | null
  decisao_pipeline: "validado" | "em_revisao"
  decisao_final: "validado" | "invalido" | null
  motivo_em_revisao: string | null
  created_at: string
}

export interface MidiaInternaAtendimento {
  id: string
  tipo: "imagem" | "audio" | "documento"
  nome_arquivo: string
  media_object_key: string
  media_url: string | null
  created_at: string
}

export interface AtendimentoOperacional {
  id: string
  numero_curto: number
  estado: EstadoAtendimento
  tipo_atendimento: TipoAtendimento | null
  urgencia: Urgencia | null
  data_desejada: string | null
  horario_desejado: string | null
  duracao_horas: number | string | null
  endereco: string | null
  bairro: string | null
  endereco_formatado: string | null
  latitude: number | string | null
  longitude: number | string | null
  place_id: string | null
  tipo_local: string | null
  forma_pagamento: string | null
  valor_acordado: number | string | null
  valor_final: number | string | null
  motivo_perda: MotivoPerda | null
  motivo_perda_obs: string | null
  pix_status: PixStatus | null
  ia_pausada: boolean
  ia_pausada_motivo: IaPausadaMotivo | null
  responsavel_atual: ResponsavelAtual
  proxima_acao_esperada: string | null
  motivo_escalada: string | null
  resumo_operacional: string | null
  sinais_qualificacao: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ServicoFechado {
  id: string
  programa_id: string
  duracao_id: string
  nome: string
  duracao_nome: string
  preco_snapshot: number
  created_at: string
}

/** Fetiche registrado num atendimento (composição). preco_snapshot null = incluso. */
export interface FeticheFechado {
  id: string
  fetiche_id: string
  nome: string
  preco_snapshot: number | null
  created_at: string
}

export interface AtendimentoDetalheResponse {
  atendimento: AtendimentoOperacional
  cliente: {
    id: string
    nome: string | null
    telefone: string
  }
  modelo: {
    id: string
    nome: string
  }
  bloqueio: BloqueioAgenda | null
  mensagens: MensagemAtendimento[]
  eventos: EventoAtendimento[]
  comprovantes_pix: ComprovantePixResumo[]
  servicos: ServicoFechado[]
  fetiches: FeticheFechado[]
  midias_internas: MidiaInternaAtendimento[]
}

export type EstadoGrupo = "Qualificando" | "Aguardando"
export type EstadoFiltro = "abertos" | "todos" | EstadoGrupo | EstadoAtendimento

/** Recorte financeiro de um modelo dentro do filtro atual (GET /atendimentos/resumo). */
export interface ResumoModeloAtendimentos {
  modelo_id: string
  modelo_nome: string
  fechados: number
  faturamento_bruto_brl: number
  ticket_medio_brl: number | null
}

export interface ResumoEstadoAtendimentos {
  estado: EstadoAtendimento
  total: number
  faturamento_bruto_brl: number
}

/** Agregado do recorte atual: faturamento bruto dos Fechados + contagens. */
export interface ResumoAtendimentos {
  total: number
  fechados: number
  faturamento_bruto_brl: number
  ticket_medio_brl: number | null
  por_modelo: ResumoModeloAtendimentos[]
  por_estado: ResumoEstadoAtendimentos[]
}
export type TipoFiltro = "todos" | TipoAtendimento
export type UrgenciaFiltro = "todas" | Urgencia
export type IaFiltro = "todos" | "ativa" | "pausada"
export type QualificacaoFiltro = "todos" | "completa" | "incompleta"

/** Período unificado do painel (preset nomeado + range custom). Ver `./filtros`. */
export type PeriodoFiltro = PeriodoSelecionado

export interface FiltrosAtendimentos {
  busca: string
  estado: EstadoFiltro
  tipo: TipoFiltro
  urgencia: UrgenciaFiltro
  ia: IaFiltro
  qualificacao: QualificacaoFiltro
  periodo: PeriodoFiltro
  /** Multi-seleção de modelo. Vazio = todas (sem filtro). */
  modeloIds: string[]
}

export type EstadoKanbanDestino = "Qualificado" | "Aguardando_confirmacao" | "Em_execucao"

export interface EditarDadosPayload {
  tipo_atendimento?: TipoAtendimento | null
  urgencia?: Urgencia | null
  data_desejada?: string | null
  horario_desejado?: string | null
  duracao_horas?: number | null
  endereco?: string | null
  bairro?: string | null
  tipo_local?: string | null
  forma_pagamento?: string | null
  valor_acordado?: number | null
  endereco_formatado?: string | null
  latitude?: number | null
  longitude?: number | null
  place_id?: string | null
}

export interface CorrigirRegistroPayload {
  novo_resultado: "Fechado" | "Perdido"
  valor_final?: number | null
  motivo?: MotivoPerda | null
  observacao?: string | null
  confirmar_alteracao_bloqueio_finalizado?: boolean
}

export interface CriarAtendimentoRequest {
  cliente_id: string
  modelo_id: string
}

export interface AtendimentoCriadoResponse {
  id: string
  numero_curto: number
  estado: EstadoAtendimento
  cliente_id: string
  modelo_id: string
  conversa_id: string
}

export type CriarAtendimentoResultado =
  | { tipo: "criado"; atendimento: AtendimentoCriadoResponse }
  | { tipo: "existente"; atendimento_id: string }

export interface TiposLocalResponse {
  items: string[]
}

export interface ContagemTipoLocalResponse {
  contagem: number
}
