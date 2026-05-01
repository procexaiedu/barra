import type {
  EstadoAtendimento,
  IaPausadaMotivo,
  TipoAtendimento,
  Urgencia,
} from "@/tipos/atendimentos"

type BadgeVariant = "active" | "paused" | "handoff" | "revisao" | "closed" | "lost"

export const estadoLabel: Record<EstadoAtendimento, string> = {
  Novo: "Novo",
  Triagem: "Triagem",
  Qualificado: "Qualificado",
  Aguardando_confirmacao: "Aguardando confirmação",
  Confirmado: "Confirmado",
  Em_execucao: "Em execução",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export const tipoLabel: Record<TipoAtendimento, string> = {
  interno: "interno",
  externo: "externo",
}

export const urgenciaLabel: Record<Urgencia, string> = {
  imediato: "imediato",
  agendado: "agendado",
  indefinido: "indefinido",
  estimado: "estimado",
}

export const motivoIaLabel: Record<IaPausadaMotivo, string> = {
  pix_em_revisao: "Em revisão",
  handoff_ia: "Em handoff",
  modelo_em_atendimento: "Pausada",
}

export function badgeForEstado(estado: EstadoAtendimento): BadgeVariant {
  if (estado === "Fechado") return "closed"
  if (estado === "Perdido") return "lost"
  return "active"
}

export function badgeForIa(motivo: IaPausadaMotivo | null): BadgeVariant {
  if (motivo === "pix_em_revisao") return "revisao"
  if (motivo === "handoff_ia") return "handoff"
  return "paused"
}

export function valorAusente<T>(valor: T | null | undefined, format?: (v: T) => string) {
  if (valor === null || valor === undefined || valor === "") return "Não informado"
  return format ? format(valor) : String(valor)
}

export function resumoPayload(payload: Record<string, unknown>) {
  const entries = Object.entries(payload).filter(([, value]) => value !== null && value !== undefined)
  if (entries.length === 0) return "Sem payload"
  return entries.slice(0, 3).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")
}
