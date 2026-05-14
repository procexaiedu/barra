import type { BloqueioAgenda } from "@/tipos/agenda"

/**
 * Classificação visual da agenda:
 * - Agendamento (bloqueio com atendimento vinculado) → verde (success-500 / state-closed).
 * - Bloqueio puro (sem atendimento) → âmbar (warn-500 / state-handoff).
 * - cancelado / concluido têm precedência sobre as duas categorias acima.
 *
 * Tokens canônicos do design system (ver `.claude/designsystem/tokens.md`).
 * NÃO USAR `emerald-*`, `amber-*`, `sky-*` crus.
 */

export function ehAgendamento(b: BloqueioAgenda): boolean {
  return Boolean(b.atendimento_id)
}

/**
 * Combinação completa de border-l + bg para o card do bloqueio.
 * Use em GradeSemanal.tsx e onde quer que o card seja renderizado inteiro.
 */
export function estiloCardCompleto(b: BloqueioAgenda): string {
  if (b.estado === "cancelado") {
    return "border-l-[3px] border-l-ink-500/30 bg-ink-500/5 opacity-50"
  }
  if (b.estado === "concluido") {
    return "border-l-[3px] border-l-ink-500/50 bg-ink-500/10"
  }
  if (ehAgendamento(b)) {
    return "border-l-[3px] border-l-success-500 bg-success-500/10"
  }
  return "border-l-[3px] border-l-warn-500 bg-warn-500/10"
}

/**
 * Só a borda (sem fundo) — usado nos cards compactos do BloqueioAgenda.
 */
export function bordaCompacto(b: BloqueioAgenda): string {
  if (b.estado === "cancelado") return "border-l-[3px] border-l-ink-500/30"
  if (b.estado === "concluido") return "border-l-[3px] border-l-ink-500/50"
  if (ehAgendamento(b)) return "border-l-[3px] border-l-success-500"
  return "border-l-[3px] border-l-warn-500"
}

/**
 * Bullet/dot de estado: usado em previews compactos (header de dia, linha do mês).
 */
export function dotEstado(b: BloqueioAgenda): string {
  if (b.estado === "cancelado") return "bg-ink-500/30"
  if (b.estado === "concluido") return "bg-ink-500/50"
  if (ehAgendamento(b)) return "bg-success-500"
  return "bg-warn-500"
}
