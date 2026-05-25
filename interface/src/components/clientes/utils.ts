import type {
  DirecaoMensagem,
  EstadoAtendimento,
  FormaPagamento,
  MotivoPerda,
} from "@/tipos/clientes"

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
  Em_execucao: "Em atendimento",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export const direcaoLabel: Record<DirecaoMensagem, string> = {
  cliente: "cliente",
  ia: "IA",
  modelo_manual: "modelo",
}

export const formaPagamentoLabel: Record<FormaPagamento, string> = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  outro: "Outro",
  cartao: "Cartão",
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

/**
 * Aplica máscara visual (XX) XXXXX-XXXX a partir de dígitos arbitrários do usuário.
 * Aceita entrada parcial; trunca em 11 dígitos (DDD + 9 dígitos).
 */
export function aplicarMascaraTelefone(input: string): string {
  const digitos = input.replace(/\D/g, "").slice(0, 11)
  if (digitos.length === 0) return ""
  if (digitos.length <= 2) return `(${digitos}`
  if (digitos.length <= 6) return `(${digitos.slice(0, 2)}) ${digitos.slice(2)}`
  if (digitos.length <= 10) {
    return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 6)}-${digitos.slice(6)}`
  }
  return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 7)}-${digitos.slice(7)}`
}

/**
 * Normaliza entrada visual de telefone para E.164 BR (55 + DDD + 8 ou 9 dígitos).
 * Retorna null se inválido.
 */
export function normalizarTelefoneE164(input: string): string | null {
  let digitos = input.replace(/\D/g, "")
  if (digitos.startsWith("55") && (digitos.length === 12 || digitos.length === 13)) {
    return digitos
  }
  if (digitos.length === 10 || digitos.length === 11) {
    digitos = `55${digitos}`
    return digitos
  }
  return null
}
