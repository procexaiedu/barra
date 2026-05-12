export type StatusModelo = "ativa" | "pausada" | "inativa"
export type TipoAtendimento = "interno" | "externo"
export type TipoMidia = "foto" | "video"
export type AbaModelo = "perfil" | "midia"
export type FiltroStatusModelo = "todos" | StatusModelo
export type FiltroEvolution = "todos" | "pareada" | "nao_pareada"
export type FiltroTipoAtendimento = "todos" | TipoAtendimento
export type EvolutionStatus = "desconectado" | "pareando" | "conectado"

export interface ModeloIndicadores {
  atendimentos_abertos: number
  conversas_ia_pausada: number
  ultimo_handoff_em: string | null
}

export interface ModeloListaItem {
  id: string
  nome: string
  numero_whatsapp: string
  status: StatusModelo
  evolution_instance_id: string | null
  evolution_status: EvolutionStatus
  evolution_pareado_em: string | null
  coordenacao_chat_id: string | null
  foto_perfil_url: string | null
  indicadores: ModeloIndicadores
}

export interface ModelosListaResponse {
  items: ModeloListaItem[]
  next_cursor: string | null
}

export interface ModeloDetalhe {
  id: string
  nome: string
  idade: number
  numero_whatsapp: string
  status: StatusModelo
  evolution_instance_id: string | null
  evolution_status: EvolutionStatus
  evolution_pareado_em: string | null
  coordenacao_chat_id: string | null
  coordenacao_verificada_em: string | null
  valor_padrao: number
  percentual_repasse: number | null
  chave_pix: string | null
  titular_chave: string | null
  idiomas: string[]
  localizacao_operacional: string | null
  endereco_formatado: string | null
  latitude: number | null
  longitude: number | null
  place_id: string | null
  tipo_atendimento_aceito: TipoAtendimento[]
  foto_perfil_object_key: string | null
  foto_perfil_url: string | null
  created_at: string
  updated_at: string
}

export interface MidiaItem {
  id: string
  modelo_id: string
  tipo: TipoMidia
  tag: string
  bucket: string
  object_key: string
  aprovada: boolean
  url_assinada: string
  created_at: string
}

/** Duração reutilizável do catálogo (1 hora, 2 horas, Pernoite…). */
export interface Duracao {
  id: string
  nome: string
  ordem: number
}

export interface DuracaoInput {
  nome: string
  ordem?: number
}

/** Programa do catálogo global da agência. */
export interface Programa {
  id: string
  nome: string
  categoria: string | null
}

export interface ProgramaInput {
  nome: string
  categoria?: string | null
}

/** Combinação programa+duração com preço definido para a modelo. */
export interface ProgramaModeloVinculo {
  programa_id: string
  duracao_id: string
  nome: string
  duracao_nome: string
  categoria: string | null
  preco: number
}

export interface WhatsappStatusResponse {
  instance_id: string | null
  status: EvolutionStatus
  pareado_em: string | null
}

export interface ModeloDetalheResponse {
  modelo: ModeloDetalhe
  midia: MidiaItem[]
  programas: ProgramaModeloVinculo[]
  evolution: WhatsappStatusResponse
  indicadores: ModeloIndicadores
}

export interface CriarModeloInput {
  nome: string
  idade: number
  numero_whatsapp: string
  valor_padrao: number
  percentual_repasse?: number | null
  chave_pix?: string | null
  titular_chave?: string | null
  idiomas: string[]
  localizacao_operacional?: string | null
  endereco_formatado?: string | null
  latitude?: number | null
  longitude?: number | null
  place_id?: string | null
  tipo_atendimento_aceito: TipoAtendimento[]
}

export interface PatchModeloInput {
  nome?: string
  idade?: number
  numero_whatsapp?: string
  valor_padrao?: number
  percentual_repasse?: number | null
  chave_pix?: string | null
  titular_chave?: string | null
  idiomas?: string[]
  localizacao_operacional?: string | null
  endereco_formatado?: string | null
  latitude?: number | null
  longitude?: number | null
  place_id?: string | null
  tipo_atendimento_aceito?: TipoAtendimento[]
  status?: StatusModelo
  coordenacao_chat_id?: string | null
}

export interface FiltrosModelos {
  busca: string
  status: FiltroStatusModelo
  evolution: FiltroEvolution
  tipo: FiltroTipoAtendimento
}

export interface MidiaInput {
  tipo: TipoMidia
  tag: string
  object_key: string
  aprovada: boolean
}

export interface UploadUrlResponse {
  object_key: string
  upload_url: string
  expires_in: number
}

export interface ConectarWhatsappResponse {
  status: EvolutionStatus | string
  instance_id: string
  qr_code: string | null
}

export interface PausarModeloResponse {
  modelo_id: string
  status: "pausada"
  conversas_pausadas: number
  em_execucao_em_curso: number
  card_enviado: boolean
}

export interface AtivarModeloResponse {
  modelo_id: string
  status: "ativa"
  conversas_pausadas_pendentes: number
}
