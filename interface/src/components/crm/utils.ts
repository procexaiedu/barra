import type {
  DirecaoMensagem,
  EstadoAtendimento,
  MotivoPerda,
} from "@/tipos/crm"

type BadgeVariant = "active" | "paused" | "handoff" | "revisao" | "closed" | "lost"

export const motivoPerdaLabel: Record<MotivoPerda, string> = {
  preco: "Preço",
  sumiu: "Sumiu",
  risco: "Risco",
  indisponibilidade: "Indisponibilidade",
  fora_de_area: "Fora de área",
  outro: "Outro",
}

export const estadoAtendimentoLabel: Record<EstadoAtendimento, string> = {
  Novo: "Novo",
  Triagem: "Triagem",
  Qualificado: "Qualificado",
  Aguardando_confirmacao: "Aguardando confirmação",
  Confirmado: "Confirmado",
  Em_execucao: "Em execução",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export const direcaoLabel: Record<DirecaoMensagem, string> = {
  cliente: "cliente",
  ia: "IA",
  modelo_manual: "modelo",
}

export function badgeForEstado(estado: EstadoAtendimento): BadgeVariant {
  if (estado === "Fechado") return "closed"
  if (estado === "Perdido") return "lost"
  return "active"
}

export function truncar(texto: string, max: number): string {
  if (texto.length <= max) return texto
  return `${texto.slice(0, max - 1)}…`
}
