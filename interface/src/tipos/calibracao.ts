// Espelho manual dos DTOs de barra/calibracao/schemas.py (sem geracao OpenAPI ainda).

export interface RodadaResumo {
  id: string
  nome: string
  created_at: string
  total_falas: number
}

export interface RodadasResponse {
  rodadas: RodadaResumo[]
}

export interface MeuRotulo {
  passou: boolean
  observacao: string | null
}

export interface FalaParaRotular {
  id: string // PK da fala — usada no PUT /rotulos
  fala_id: string // conversa_id::idx
  conversa_id: string
  cenario: string
  texto_resposta: string
  historico: string[]
  meu_rotulo: MeuRotulo | null
}

export interface FalasResponse {
  rodada: RodadaResumo
  rotulador: string
  falas: FalaParaRotular[]
}

export interface ExportResponse {
  golden: string
  total: number
  avisos: string[]
}
