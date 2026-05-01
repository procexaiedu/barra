export type DecisaoPipeline = "validado" | "em_revisao"
export type DecisaoFinal = "validado" | "invalido" | null

export type MotivoRevisao =
  | "valor_divergente"
  | "fora_da_janela"
  | "conta_destino_invalida"
  | "duplicado"
  | "ocr_falhou"
  | "outro"

export type MotivoRejeicao =
  | "valor_incorreto"
  | "comprovante_ilegivel"
  | "conta_destino_errada"
  | "duplicado"
  | "fora_da_janela"
  | "outro"

export type FiltroStatusPix =
  | "pendentes"
  | "validado_auto"
  | "validado_manual"
  | "rejeitado"
  | "todos"

export type FiltroPeriodoPix = "todos" | "24h" | "7d" | "30d"

export type TipoChave = "cpf" | "cnpj" | "email" | "telefone" | "aleatoria"

export type EstadoAtendimento =
  | "Triagem"
  | "Aguardando_pix"
  | "Aguardando_confirmacao"
  | "Confirmado"
  | "Em_execucao"
  | "Fechado"
  | "Perdido"
  | string

export type TipoAtendimento = "interno" | "externo"
export type Urgencia = "imediato" | "agendado" | "indefinido" | "estimado"

export interface ClienteResumoPix {
  id: string
  nome: string | null
  telefone: string
}

export interface ModeloResumoPix {
  id: string
  nome: string
}

export interface AtendimentoResumoPix {
  id: string
  numero_curto: number
  estado: EstadoAtendimento
  tipo_atendimento: TipoAtendimento | null
  urgencia: Urgencia | null
  valor_acordado: number | null
  proxima_acao_esperada: string | null
}

export interface AtendimentoListaPix {
  id: string
  numero_curto: number
  estado: EstadoAtendimento
}

export interface ConversaResumoPix {
  id: string
}

export interface ChecagemPix {
  chave: string
  label: string
  passou: boolean
  motivo: string | null
}

export interface EventoPix {
  id: string
  tipo: string
  origem: string
  autor: string
  resumo: string | null
  payload: Record<string, unknown>
  created_at: string
}

export interface PixListaItem {
  id: string
  cliente: ClienteResumoPix
  modelo: ModeloResumoPix
  atendimento: AtendimentoListaPix | null
  decisao_pipeline: DecisaoPipeline
  decisao_final: DecisaoFinal
  motivo_em_revisao: MotivoRevisao | null
  valor_extraido: number | null
  created_at: string
}

export interface PixListaResponse {
  items: PixListaItem[]
  next_cursor: string | null
}

export interface PixDetalhe {
  id: string
  decisao_pipeline: DecisaoPipeline
  decisao_final: DecisaoFinal
  motivo_em_revisao: MotivoRevisao | null
  valor_extraido: number | null
  horario_transacao: string | null
  titular_extraido: string | null
  documento_extraido: string | null
  chave_extraida: string | null
  tipo_chave: TipoChave | null
  hash_duplicidade: string | null
  nome_arquivo: string
  tamanho: number
  mime_type: string
  comprovante_disponivel: boolean
  created_at: string
}

export interface PixDetalheResponse {
  pix: PixDetalhe
  cliente: ClienteResumoPix
  modelo: ModeloResumoPix
  conversa: ConversaResumoPix | null
  atendimento: AtendimentoResumoPix | null
  checagens: ChecagemPix[]
  eventos: EventoPix[]
}

export interface ComprovanteUrlResponse {
  url: string
  expires_at: string
}

export interface RejeitarPixInput {
  motivo: MotivoRejeicao
  observacao: string | null
}

export interface FiltrosPix {
  busca: string
  status: FiltroStatusPix
  modelo_id: string | "todas"
  motivo_em_revisao: MotivoRevisao | "todos"
  periodo: FiltroPeriodoPix
  atendimento_id: string | null
}
