import { formatRotulo } from "@/lib/formatters"
import type {
  EstadoAtendimento,
  EventoAtendimento,
  IaPausadaMotivo,
  TipoAtendimento,
  Urgencia,
} from "@/tipos/atendimentos"

type BadgeVariant = "active" | "paused" | "handoff" | "info" | "revisao" | "closed" | "lost"

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
  remoto: "Vídeo chamada",
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

// Cor de estado — fonte única para que badge, faixa de acento e ponto de legenda
// concordem na mesma cor em lista, kanban e detalhe (tokens --state-*):
// Qualificando=dourado · Aguardando=âmbar · Em atendimento=azul · Fechado=verde · Perdido=vermelho.
const ESTADO_VARIANT: Record<EstadoAtendimento, BadgeVariant> = {
  Novo: "active",
  Triagem: "active",
  Qualificado: "active",
  Aguardando_confirmacao: "handoff",
  Confirmado: "handoff",
  Em_execucao: "info",
  Fechado: "closed",
  Perdido: "lost",
}

type EstadoVariant = "active" | "handoff" | "info" | "closed" | "lost"

export type CorEstado = { faixa: string; ponto: string; texto: string }

const VARIANT_COR: Record<EstadoVariant, CorEstado> = {
  active:  { faixa: "border-l-state-active",  ponto: "bg-state-active",  texto: "text-state-active"  },
  handoff: { faixa: "border-l-state-handoff", ponto: "bg-state-handoff", texto: "text-state-handoff" },
  info:    { faixa: "border-l-state-info",    ponto: "bg-state-info",    texto: "text-state-info"    },
  closed:  { faixa: "border-l-state-closed",  ponto: "bg-state-closed",  texto: "text-state-closed"  },
  lost:    { faixa: "border-l-state-lost",    ponto: "bg-state-lost",    texto: "text-state-lost"    },
}

export function badgeForEstado(estado: EstadoAtendimento): BadgeVariant {
  return ESTADO_VARIANT[estado]
}

export function corEstado(estado: EstadoAtendimento): CorEstado {
  return VARIANT_COR[ESTADO_VARIANT[estado] as EstadoVariant]
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
  // Remoto (vídeo chamada): sem deslocamento e sem Pix — só valor e horário.
  if (tipo === "remoto")
    return TODOS_SINAIS.filter((s) => s.chave !== "envia_pix" && s.chave !== "informa_local")
  return TODOS_SINAIS
}

export function formatEnum(valor: string | null | undefined): string | null {
  if (!valor) return null
  if (VALOR_LEGIVEL_MAP[valor]) return VALOR_LEGIVEL_MAP[valor]
  return formatRotulo(valor)
}

// --- Linha do tempo (eventos do atendimento) ---

// A extração da IA é telemetria interna (atualização de contexto), não um marco
// de negócio. O Fernando vê marcos por padrão; a telemetria fica atrás de um toggle.
export function categoriaEvento(tipo: string): "marco" | "telemetria" {
  return tipo === "extracao_registrada" ? "telemetria" : "marco"
}

// Chave de ícone por tipo de evento; o componente mapeia para um ícone Lucide.
export function iconeEvento(tipo: string): string {
  if (tipo === "transicao_estado") return "estado"
  if (tipo.startsWith("pix") || tipo.startsWith("pipeline") || tipo === "comprovante_recebido") return "pix"
  if (tipo === "atendimento_fechado") return "fechado"
  if (tipo === "atendimento_perdido") return "perdido"
  if (tipo === "cliente_chegou" || tipo === "saida_confirmada" || tipo === "aviso_saida") return "chegada"
  if (tipo === "handoff_aberto" || tipo === "ia_pausada") return "pausa"
  if (tipo === "handoff_fechado" || tipo === "ia_devolvida") return "retomada"
  if (tipo.startsWith("bloqueio")) return "bloqueio"
  if (tipo === "extracao_registrada") return "ia"
  return "default"
}

// Descrição em linguagem de negócio para a linha do tempo. Para a extração da IA,
// usa a "próxima ação esperada" (texto humano) em vez do payload técnico.
export function descricaoEvento(evento: EventoAtendimento): string | null {
  const p = evento.payload ?? {}
  if (evento.tipo === "transicao_estado") {
    const para = typeof p.para === "string"
      ? (estadoLabel[p.para as EstadoAtendimento] ?? formatRotulo(p.para) ?? p.para)
      : null
    return para ? `Avançou para ${para}` : null
  }
  const proxima = p["proxima_acao_esperada"]
  if (typeof proxima === "string" && proxima.trim()) return proxima.trim()
  return resumoPayload(p as Record<string, unknown>)
}
