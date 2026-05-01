import type {
  ChecagemPix,
  DecisaoFinal,
  DecisaoPipeline,
  EstadoAtendimento,
  EventoPix,
  FiltroStatusPix,
  MotivoRejeicao,
  MotivoRevisao,
  PixDetalhe,
  PixListaItem,
  TipoChave,
} from "@/tipos/pix"

type BadgeVariant = "active" | "paused" | "handoff" | "revisao" | "closed" | "lost"

export type StatusItemPix = "em_revisao" | "validado_auto" | "validado_manual" | "rejeitado"

export interface BadgePix {
  variant: BadgeVariant
  label: string
}

export const motivoRevisaoLabel: Record<MotivoRevisao, string> = {
  valor_divergente: "valor_divergente",
  fora_da_janela: "fora_da_janela",
  conta_destino_invalida: "conta_destino_invalida",
  duplicado: "duplicado",
  ocr_falhou: "ocr_falhou",
  outro: "outro",
}

export const motivoRevisaoFiltroOptions: { value: MotivoRevisao | "todos"; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "valor_divergente", label: "valor_divergente" },
  { value: "fora_da_janela", label: "fora_da_janela" },
  { value: "conta_destino_invalida", label: "conta_destino_invalida" },
  { value: "duplicado", label: "duplicado" },
  { value: "ocr_falhou", label: "ocr_falhou" },
  { value: "outro", label: "outro" },
]

export const motivoRejeicaoOptions: { value: MotivoRejeicao; label: string }[] = [
  { value: "valor_incorreto", label: "Valor incorreto" },
  { value: "comprovante_ilegivel", label: "Comprovante ilegível" },
  { value: "conta_destino_errada", label: "Conta destino errada" },
  { value: "duplicado", label: "Comprovante duplicado" },
  { value: "fora_da_janela", label: "Fora da janela temporal" },
  { value: "outro", label: "Outro" },
]

export const statusFiltroOptions: { value: FiltroStatusPix; label: string }[] = [
  { value: "pendentes", label: "Pendentes" },
  { value: "validado_auto", label: "Validado automaticamente" },
  { value: "validado_manual", label: "Validado por Fernando" },
  { value: "rejeitado", label: "Rejeitado" },
  { value: "todos", label: "Todos" },
]

export const periodoFiltroOptions = [
  { value: "todos", label: "Todos" },
  { value: "24h", label: "24 h" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
] as const

export const tipoChaveLabel: Record<TipoChave, string> = {
  cpf: "CPF",
  cnpj: "CNPJ",
  email: "e-mail",
  telefone: "telefone",
  aleatoria: "aleatória",
}

export function statusItemPix(
  decisaoPipeline: DecisaoPipeline,
  decisaoFinal: DecisaoFinal
): StatusItemPix {
  if (decisaoFinal === "validado") return "validado_manual"
  if (decisaoFinal === "invalido") return "rejeitado"
  if (decisaoPipeline === "validado") return "validado_auto"
  return "em_revisao"
}

export function badgeForStatusPix(status: StatusItemPix): BadgePix {
  switch (status) {
    case "em_revisao":
      return { variant: "revisao", label: "Em revisão" }
    case "validado_auto":
      return { variant: "closed", label: "Validado auto" }
    case "validado_manual":
      return { variant: "closed", label: "Validado por Fernando" }
    case "rejeitado":
      return { variant: "lost", label: "Rejeitado" }
  }
}

export function isPendente(item: PixListaItem | PixDetalhe): boolean {
  return item.decisao_pipeline === "em_revisao" && item.decisao_final === null
}

export function isRejeitado(item: PixListaItem | PixDetalhe): boolean {
  return item.decisao_final === "invalido"
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—"
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(kb >= 100 ? 0 : kb >= 10 ? 1 : 1)} KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(mb >= 100 ? 0 : mb >= 10 ? 1 : 2)} MB`
  return `${(mb / 1024).toFixed(2)} GB`
}

export const estadoAtendimentoLabel: Record<string, string> = {
  Novo: "Novo",
  Triagem: "Triagem",
  Qualificado: "Qualificado",
  Aguardando_pix: "Aguardando Pix",
  Aguardando_confirmacao: "Aguardando confirmação",
  Confirmado: "Confirmado",
  Em_execucao: "Em execução",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export function badgeForEstadoAtendimento(estado: EstadoAtendimento): BadgeVariant {
  if (estado === "Fechado") return "closed"
  if (estado === "Perdido") return "lost"
  return "active"
}

export function isAtendimentoTerminal(estado: EstadoAtendimento): boolean {
  return estado === "Fechado" || estado === "Perdido"
}

export interface EventoVisual {
  label: string
  icone: "Inbox" | "CheckCircle2" | "AlertCircle" | "XCircle" | "RefreshCw" | "Dot"
  cor: "muted" | "success" | "warn" | "danger"
}

export const eventoVisualMap: Record<string, EventoVisual> = {
  comprovante_recebido: { label: "Comprovante recebido", icone: "Inbox", cor: "muted" },
  pipeline_validado: { label: "Pipeline validou automaticamente", icone: "CheckCircle2", cor: "success" },
  pipeline_em_revisao: { label: "Pipeline marcou em revisão", icone: "AlertCircle", cor: "warn" },
  pix_validado_manual: { label: "Validado por Fernando", icone: "CheckCircle2", cor: "success" },
  pix_rejeitado: { label: "Rejeitado por Fernando", icone: "XCircle", cor: "danger" },
  pix_reaberto: { label: "Reaberto por Fernando", icone: "RefreshCw", cor: "warn" },
}

export function eventoVisual(evt: EventoPix): EventoVisual {
  if (eventoVisualMap[evt.tipo]) return eventoVisualMap[evt.tipo]
  const label = evt.tipo
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ")
  return { label, icone: "Dot", cor: "muted" }
}

export function checagemLabel(c: ChecagemPix): string {
  if (c.label) return c.label
  return c.chave
    .split("_")
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ")
}
