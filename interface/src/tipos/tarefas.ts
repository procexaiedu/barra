/** Tipos do Módulo de Tarefas (ADR 0017). Espelho manual dos DTOs do backend
 *  (`api/src/barra/dominio/tarefas/schemas.py`) — não há geração automática ainda. */

export type StatusTarefa = "a_fazer" | "fazendo" | "feita"
export type PrioridadeTarefa = "baixa" | "media" | "alta"
/** Ator polimórfico. No P0 só `usuario`/`modelo` são selecionáveis; `vendedor`
 *  fica reservado para quando a tabela do ADR 0012 existir. */
export type AtorTipo = "usuario" | "modelo" | "vendedor"
export type PrazoFiltro = "hoje" | "semana" | "atrasadas" | "hoje_e_atrasadas" | "todos"

export interface AtorRef {
  tipo: AtorTipo
  id: string
  /** Resolvido por JOIN na leitura; null se o ator foi removido. */
  nome: string | null
}

export interface Tarefa {
  id: string
  titulo: string
  descricao: string | null
  status: StatusTarefa
  prioridade: PrioridadeTarefa
  /** `YYYY-MM-DD` (sem hora) ou null (backlog). */
  prazo: string | null
  criado_por: AtorRef
  atribuido: AtorRef | null
  concluida_em: string | null
  created_at: string
  updated_at: string
}

export interface TarefasListaResponse {
  items: Tarefa[]
}

export interface CriarTarefaInput {
  titulo: string
  descricao?: string | null
  prioridade?: PrioridadeTarefa
  prazo?: string | null
  atribuido_tipo?: AtorTipo | null
  atribuido_id?: string | null
}

export interface PatchTarefaInput {
  titulo?: string
  descricao?: string | null
  status?: StatusTarefa
  prioridade?: PrioridadeTarefa
  prazo?: string | null
  atribuido_tipo?: AtorTipo | null
  atribuido_id?: string | null
}

export interface ResponsavelOpcao {
  tipo: AtorTipo
  id: string
  nome: string
}

export interface ResponsaveisResponse {
  items: ResponsavelOpcao[]
}
