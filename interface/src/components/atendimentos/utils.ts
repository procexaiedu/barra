import { formatRotulo } from "@/lib/formatters"
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
  Em_execucao: "Em atendimento",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

export const tipoLabel: Record<TipoAtendimento, string> = {
  interno: "No local da modelo",
  externo: "No local do cliente",
}

export const urgenciaLabel: Record<Urgencia, string> = {
  imediato: "Agora",
  agendado: "Marcado",
  indefinido: "Indefinido",
  estimado: "Estimado",
}

export const motivoIaLabel: Record<IaPausadaMotivo, string> = {
  pix_em_revisao: "Pix em revisão",
  handoff_ia: "Aguardando você",
  modelo_em_atendimento: "Modelo atendendo",
}

const MOTIVO_ESCALADA_TEXTO: Record<IaPausadaMotivo, string> = {
  pix_em_revisao: "Pix duvidoso, precisa da sua decisão",
  handoff_ia: "IA escalou para você",
  modelo_em_atendimento: "Modelo passou do tempo previsto",
}

const MOTIVO_TEXTO_LIVRE: Record<string, string> = {
  comportamento_ambiguo: "Comportamento ambíguo",
  cliente_chegou: "Cliente chegou",
  duvida_localizacao: "Dúvida sobre localização",
  duvida_pagamento: "Dúvida sobre pagamento",
  cliente_silencioso: "Cliente silencioso",
  fora_de_area: "Fora de área",
  preco_negociacao: "Negociação de preço",
  pix_duvidoso: "Pix duvidoso",
  saida_confirmada: "Saída confirmada",
  tempo_excedido: "Tempo previsto excedido",
}

export function motivoExibido(
  motivoEscalada: string | null | undefined,
  categoria: IaPausadaMotivo | null | undefined,
): string | null {
  if (motivoEscalada && motivoEscalada in MOTIVO_ESCALADA_TEXTO) {
    return MOTIVO_ESCALADA_TEXTO[motivoEscalada as IaPausadaMotivo]
  }
  if (motivoEscalada && motivoEscalada in MOTIVO_TEXTO_LIVRE) {
    return MOTIVO_TEXTO_LIVRE[motivoEscalada]
  }
  if (motivoEscalada && !motivoEscalada.includes("_")) return motivoEscalada
  if (motivoEscalada) {
    return formatRotulo(motivoEscalada) ?? (categoria ? MOTIVO_ESCALADA_TEXTO[categoria] : null)
  }
  return categoria ? MOTIVO_ESCALADA_TEXTO[categoria] : null
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

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const VALOR_LEGIVEL_MAP: Record<string, string> = {
  Aguardando_confirmacao: "Aguardando confirmação",
  Em_execucao: "Em atendimento",
  em_atendimento: "Em atendimento",
  pix_em_revisao: "Pix em revisão",
  modelo_em_atendimento: "Modelo atendendo",
  handoff_ia: "Aguardando você",
  cron_em_execucao: "Tempo de atendimento",
  duracao_em_execucao_dentro_do_combinado: "Duração dentro do combinado",
  foto_portaria: "Foto da portaria",
  aviso_saida: "Aviso de saída",
  extracao_ia: "Extração da IA",
  pipeline_pix: "Pipeline Pix",
  modelo_manual: "Modelo",
  webhook_imagem: "Webhook de imagem",
  nao_solicitado: "Não solicitado",
  fora_de_area: "Fora de área",
}

function chaveLegivel(chave: string): string {
  return chave.replaceAll("_", " ")
}

function valorLegivel(valor: unknown): string | null {
  if (valor === null || valor === undefined) return null
  if (typeof valor === "boolean") return valor ? "sim" : "não"
  if (typeof valor === "number") return String(valor)
  if (typeof valor === "string") {
    if (UUID_RE.test(valor)) return null
    if (VALOR_LEGIVEL_MAP[valor]) return VALOR_LEGIVEL_MAP[valor]
    return formatRotulo(valor) ?? valor
  }
  if (Array.isArray(valor)) {
    if (valor.length === 0) return null
    return valor.map(valorLegivel).filter(Boolean).join(", ") || null
  }
  if (typeof valor === "object") {
    const obj = valor as Record<string, unknown>
    const verdadeiros = Object.entries(obj)
      .filter(([, v]) => v === true)
      .map(([k]) => chaveLegivel(k))
    if (verdadeiros.length > 0) return verdadeiros.join(", ")
    return null
  }
  return null
}

export function resumoPayload(payload: Record<string, unknown>) {
  const entries = Object.entries(payload)
    .filter(([chave]) => !chave.endsWith("_id"))
    .map(([chave, valor]) => [chave, valorLegivel(valor)] as const)
    .filter(([, valor]) => valor !== null && valor !== "")
  if (entries.length === 0) return null
  return entries.slice(0, 4).map(([chave, valor]) => `${chaveLegivel(chave)}: ${valor}`).join(" · ")
}

const TIPO_EVENTO_LABEL: Record<string, string> = {
  transicao_estado: "Mudança de estado",
  handoff_aberto: "IA pausou",
  handoff_fechado: "IA retomou",
  ia_pausada: "IA pausou",
  ia_devolvida: "IA retomou",
  bloqueio_criado: "Bloqueio criado",
  bloqueio_atualizado: "Bloqueio atualizado",
  bloqueio_cancelado: "Bloqueio cancelado",
  bloqueio_estado_mudado: "Bloqueio mudou de estado",
  extracao_registrada: "Extração de dados pela IA",
  comprovante_recebido: "Comprovante recebido",
  pipeline_validado: "Pix validado automaticamente",
  pipeline_em_revisao: "Pix marcado para revisão",
  pix_validado_manual: "Pix validado por você",
  pix_rejeitado: "Pix rejeitado",
  pix_reaberto: "Pix reaberto",
  atendimento_fechado: "Atendimento fechado",
  atendimento_perdido: "Atendimento perdido",
  cliente_chegou: "Cliente chegou",
  saida_confirmada: "Saída confirmada",
  aviso_saida: "Cliente avisou saída",
}

const ORIGEM_LABEL: Record<string, string> = {
  agente: "IA",
  sistema: "Sistema",
  cron: "Sistema",
  pipeline_pix: "Sistema",
  webhook: "Sistema",
  painel: "Painel",
  painel_fernando: "Painel",
  manual: "Manual",
}

const AUTOR_LABEL: Record<string, string> = {
  IA: "IA",
  ia: "IA",
  agente: "IA",
  sistema: "Sistema",
  fernando: "Você",
  Fernando: "Você",
  modelo: "Modelo",
}

export function tipoEventoLabel(tipo: string): string {
  return TIPO_EVENTO_LABEL[tipo] ?? formatRotulo(tipo) ?? tipo
}

export function origemEventoLabel(origem: string): string {
  return ORIGEM_LABEL[origem] ?? formatRotulo(origem) ?? origem
}

export function autorEventoLabel(autor: string): string {
  return AUTOR_LABEL[autor] ?? autor
}

const TODOS_SINAIS: { chave: string; rotulo: string }[] = [
  { chave: "aceita_valor", rotulo: "Aceita valor" },
  { chave: "informa_local", rotulo: "Informa local" },
  { chave: "informa_horario", rotulo: "Informa horário" },
  { chave: "envia_pix", rotulo: "Envia Pix" },
]

export function sinaisParaTipo(tipo: string | null | undefined): { chave: string; rotulo: string }[] {
  if (tipo === "interno") return TODOS_SINAIS.filter((s) => s.chave !== "envia_pix")
  return TODOS_SINAIS
}

export function formatEnum(valor: string | null | undefined): string | null {
  if (!valor) return null
  if (VALOR_LEGIVEL_MAP[valor]) return VALOR_LEGIVEL_MAP[valor]
  return formatRotulo(valor)
}
