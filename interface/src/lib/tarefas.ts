import type { AtorTipo, PrioridadeTarefa, StatusTarefa } from "@/tipos/tarefas"

export const STATUS_LABEL: Record<StatusTarefa, string> = {
  a_fazer: "A fazer",
  fazendo: "Fazendo",
  feita: "Feita",
}

export const STATUS_ORDEM: StatusTarefa[] = ["a_fazer", "fazendo", "feita"]

export const PRIORIDADE_LABEL: Record<PrioridadeTarefa, string> = {
  baixa: "Baixa",
  media: "Média",
  alta: "Alta",
}

export const PRIORIDADE_ORDEM: PrioridadeTarefa[] = ["baixa", "media", "alta"]

export const ATOR_LABEL: Record<AtorTipo, string> = {
  usuario: "Operador",
  modelo: "Modelo",
  vendedor: "Vendedor",
}

/** Barra/ponto de acento por prioridade (tokens semânticos do tema). */
export const PRIORIDADE_BAR: Record<PrioridadeTarefa, string> = {
  alta: "bg-danger-500",
  media: "bg-gold-500",
  baixa: "bg-border-strong",
}

export const PRIORIDADE_TEXT: Record<PrioridadeTarefa, string> = {
  alta: "text-danger-500",
  media: "text-text-brand",
  baixa: "text-text-muted",
}

/** Acento por status — usado nos cabeçalhos das colunas do board. */
export const STATUS_ACENTO: Record<StatusTarefa, { bar: string; text: string }> = {
  a_fazer: { bar: "bg-border-strong", text: "text-text-muted" },
  fazendo: { bar: "bg-gold-500", text: "text-text-brand" },
  feita: { bar: "bg-success-500", text: "text-success-500" },
}

/** Chave composta do ator para usar no Combobox (que opera sobre strings). */
export function atorKey(tipo: AtorTipo, id: string): string {
  return `${tipo}:${id}`
}

export function parseAtorKey(key: string): { tipo: AtorTipo; id: string } {
  const idx = key.indexOf(":")
  return { tipo: key.slice(0, idx) as AtorTipo, id: key.slice(idx + 1) }
}

/** "YYYY-MM-DD" -> "DD/MM" sem passar por `Date` (evita desvio de timezone). */
export function formatPrazoCurto(prazo: string): string {
  const [, m, d] = prazo.split("-")
  return `${d}/${m}`
}
