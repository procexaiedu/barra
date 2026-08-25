import type { PeriodoSelecionado } from "@/tipos/filtros"

export type DecisaoPipeline = "validado" | "em_revisao"
export type DecisaoFinal = "validado" | "invalido" | null

/**
 * Por que ESTE comprovante ficou duvidoso — o vocabulário único dos dois caminhos
 * (ADR-0049 §5, ticket 07). Espelha
 * `barra.dominio.grupo_financeiro.comprovante.MotivoDeSuspeita`.
 *
 * ⚠️ O que existia aqui antes era um TERCEIRO vocabulário (`valor_divergente`, `ocr_falhou`,
 * `conta_destino_invalida`) que o backend nunca emitiu: `motivo_em_revisao` sempre veio como
 * prosa livre, então `motivoRevisaoLabel[prosa]` era `undefined` e a linha do motivo na lista de
 * Pix renderizava VAZIA. Agora o backend carimba o motivo canônico na frente da prosa e
 * `lerSuspeita` separa os dois.
 */
export type MotivoDeSuspeita =
  | "imagem_repetida"
  | "sem_leitura"
  | "imagem_implausivel"
  | "imagem_ilegivel"
  | "valor_abaixo_do_esperado"
  | "destino_desconhecido"
  | "titular_divergente"

/**
 * O VEREDITO humano ao rejeitar — o que Fernando concluiu, não o que a máquina suspeitou.
 * `comprovante_falso` entrou no ticket 07: o "Pix zoado" da ata não tinha palavra própria e o
 * operador era obrigado a marcar `outro`.
 */
export type MotivoRejeicao =
  | "valor_incorreto"
  | "comprovante_ilegivel"
  | "conta_destino_errada"
  | "comprovante_falso"
  | "duplicado"
  | "fora_da_janela"
  | "outro"

export type FiltroStatusPix =
  | "pendentes"
  | "validado_auto"
  | "validado_manual"
  | "rejeitado"
  | "todos"

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
  /** Prosa do backend, com o motivo canônico carimbado na frente (ver `lerSuspeita`). */
  motivo_em_revisao: string | null
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
  /** Prosa do backend, com o motivo canônico carimbado na frente (ver `lerSuspeita`). */
  motivo_em_revisao: string | null
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
  modelo_ids: string[]
  motivo_em_revisao: MotivoDeSuspeita | "todos"
  periodo: PeriodoSelecionado
  atendimento_id: string | null
}
