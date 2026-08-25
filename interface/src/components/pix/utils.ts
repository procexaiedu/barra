import { badgeForEstado } from "@/components/atendimentos/utils"
import type { EstadoAtendimento as EstadoAtendimentoCanonico } from "@/tipos/atendimentos"
import type {
  ChecagemPix,
  DecisaoFinal,
  DecisaoPipeline,
  EstadoAtendimento,
  EventoPix,
  FiltroStatusPix,
  MotivoDeSuspeita,
  MotivoRejeicao,
  PixDetalhe,
  PixListaItem,
  TipoChave,
} from "@/tipos/pix"

type BadgeVariant = "active" | "paused" | "handoff" | "info" | "revisao" | "closed" | "lost"

export type StatusItemPix = "em_revisao" | "validado_auto" | "validado_manual" | "rejeitado"

export interface BadgePix {
  variant: BadgeVariant
  label: string
}

/**
 * Como o painel chama cada suspeita — a etiqueta do vocabulário único (ADR-0049 §5, ticket 07).
 * A ordem é a `PRECEDENCIA_DA_SUSPEITA` do backend: da dúvida mais grave para a mais fraca.
 */
export const rotuloDaSuspeita: Record<MotivoDeSuspeita, string> = {
  imagem_repetida: "Foto repetida",
  sem_leitura: "Não conseguimos ler",
  imagem_implausivel: "Comprovante suspeito",
  imagem_ilegivel: "Comprovante ilegível",
  valor_abaixo_do_esperado: "Valor abaixo do esperado",
  destino_desconhecido: "Destino desconhecido",
  titular_divergente: "Titular divergente",
}

export const motivoSuspeitaFiltroOptions: { value: MotivoDeSuspeita | "todos"; label: string }[] = [
  { value: "todos", label: "Todos" },
  ...(Object.keys(rotuloDaSuspeita) as MotivoDeSuspeita[]).map((value) => ({
    value,
    label: rotuloDaSuspeita[value],
  })),
]

/**
 * O que a máquina suspeitou -> o veredito que o humano provavelmente vai dar. Espelha
 * `barra.dominio.pix.schemas.REJEICAO_SUGERIDA`; é só o pré-selecionado do diálogo de rejeição,
 * e trocar continua sendo um clique.
 */
export const rejeicaoSugerida: Record<MotivoDeSuspeita, MotivoRejeicao> = {
  imagem_repetida: "duplicado",
  sem_leitura: "comprovante_ilegivel",
  imagem_implausivel: "comprovante_falso",
  imagem_ilegivel: "comprovante_ilegivel",
  valor_abaixo_do_esperado: "valor_incorreto",
  destino_desconhecido: "conta_destino_errada",
  titular_divergente: "conta_destino_errada",
}

export const REJEICAO_PADRAO: MotivoRejeicao = "valor_incorreto"

export const motivoRejeicaoOptions: { value: MotivoRejeicao; label: string }[] = [
  { value: "valor_incorreto", label: "Valor incorreto" },
  { value: "comprovante_ilegivel", label: "Comprovante ilegível" },
  { value: "conta_destino_errada", label: "Conta destino errada" },
  { value: "comprovante_falso", label: "Comprovante falso (montagem)" },
  { value: "duplicado", label: "Comprovante duplicado" },
  { value: "fora_da_janela", label: "Fora da janela temporal" },
  { value: "outro", label: "Outro" },
]

const SEPARADOR_DA_SUSPEITA = ": "

export interface SuspeitaLida {
  /** O motivo canônico, quando o backend carimbou. `null` na prosa antiga, sem carimbo. */
  motivo: MotivoDeSuspeita | null
  /** A prosa que o revisor lê: o número, a chave como foi lida. Sempre presente. */
  detalhe: string
  /** A etiqueta curta da lista: o rótulo quando há motivo, senão a própria prosa. */
  rotulo: string
}

/**
 * Separa `"valor_abaixo_do_esperado: valor extraido 80.00 < esperado R$100"` em motivo + detalhe.
 *
 * Fail-open de propósito: toda linha gravada antes do ticket 07 tem prosa crua, e exigir o
 * carimbo transformaria o histórico inteiro em "motivo desconhecido". Sem motivo, o detalhe é a
 * prosa inteira — que é exatamente o que o operador precisava ver e não via.
 *
 * Só o PRIMEIRO separador é limite: a prosa do backend já usa ":" internamente
 * ("vision inconclusivo: finish_reason=length").
 */
export function lerSuspeita(motivoEmRevisao: string | null): SuspeitaLida {
  if (!motivoEmRevisao) return { motivo: null, detalhe: "", rotulo: "" }
  const corte = motivoEmRevisao.indexOf(SEPARADOR_DA_SUSPEITA)
  if (corte > 0) {
    const cabeca = motivoEmRevisao.slice(0, corte)
    if (cabeca in rotuloDaSuspeita) {
      const motivo = cabeca as MotivoDeSuspeita
      return {
        motivo,
        detalhe: motivoEmRevisao.slice(corte + SEPARADOR_DA_SUSPEITA.length),
        rotulo: rotuloDaSuspeita[motivo],
      }
    }
  }
  return { motivo: null, detalhe: motivoEmRevisao, rotulo: motivoEmRevisao }
}

export const statusFiltroOptions: { value: FiltroStatusPix; label: string }[] = [
  { value: "pendentes", label: "Aguardando você" },
  { value: "validado_auto", label: "Validado automaticamente" },
  { value: "validado_manual", label: "Validado por você" },
  { value: "rejeitado", label: "Rejeitado" },
  { value: "todos", label: "Todos" },
]

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
      return { variant: "revisao", label: "Aguardando você" }
    case "validado_auto":
      return { variant: "closed", label: "Validado auto" }
    case "validado_manual":
      return { variant: "closed", label: "Validado por você" }
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
  Em_execucao: "Em atendimento",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export function badgeForEstadoAtendimento(estado: EstadoAtendimento): BadgeVariant {
  // Mesma cor de estado do resto do painel (fonte única em
  // `components/atendimentos/utils`). O DTO do Pix tem união aberta e ainda
  // carrega `Aguardando_pix`, fora da canônica: aí cai no "em andamento".
  const variante: BadgeVariant | undefined = badgeForEstado(estado as EstadoAtendimentoCanonico)
  return variante ?? "active"
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
  pipeline_validado: { label: "Validado automaticamente", icone: "CheckCircle2", cor: "success" },
  pipeline_em_revisao: { label: "Marcado para revisão", icone: "AlertCircle", cor: "warn" },
  pix_validado_manual: { label: "Validado por você", icone: "CheckCircle2", cor: "success" },
  pix_rejeitado: { label: "Rejeitado por você", icone: "XCircle", cor: "danger" },
  pix_reaberto: { label: "Reaberto por você", icone: "RefreshCw", cor: "warn" },
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
