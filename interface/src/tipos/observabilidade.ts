// Espelho manual dos DTOs de api/src/barra/dominio/observabilidade/schemas.py
// (ver interface/CLAUDE.md — sem geração OpenAPI ainda).

export type VereditoAvaliacao = "bom" | "ruim"

export interface MensagemTurno {
  conteudo: string
  created_at: string
}

export interface AvaliacaoResposta {
  veredito: VereditoAvaliacao
  nota: number | null
  comentario: string | null
  avaliado_em: string
}

export interface TurnoObservabilidade {
  resposta_ia_id: string
  conversa_id: string
  atendimento_id: string | null
  numero_curto: number | null
  cliente_nome: string | null
  cliente_telefone: string
  modelo_nome: string
  mensagem_cliente: MensagemTurno | null
  resposta_ia: MensagemTurno
  avaliacao: AvaliacaoResposta | null
}

export interface TurnosObservabilidadeResponse {
  items: TurnoObservabilidade[]
  next_cursor: string | null
}

export interface AvaliarRequest {
  veredito: VereditoAvaliacao
  nota: number | null
  comentario: string | null
}
