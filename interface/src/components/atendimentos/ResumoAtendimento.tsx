"use client"

import type { ReactNode } from "react"
import Link from "next/link"
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Circle,
  CreditCard,
  MapPin,
  ReceiptText,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { formatBRL, formatData, formatDataHora, formatRotulo } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, ServicoFechado } from "@/tipos/atendimentos"
import { estadoLabel, formatEnum, motivoExibido, sinaisParaTipo, tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"

function asNumber(valor: number | string | null) {
  if (valor === null) return null
  const n = typeof valor === "number" ? valor : Number(valor)
  return Number.isFinite(n) ? n : null
}

function NaoInformado() {
  return <span className="text-text-disabled">Não informado</span>
}

export function ResumoAtendimento({ detalhe }: { detalhe: AtendimentoDetalheResponse }) {
  const atendimento = detalhe.atendimento
  const valorAcordado = asNumber(atendimento.valor_acordado)
  const sq = atendimento.sinais_qualificacao as Record<string, unknown> | null
  const sinais = sinaisParaTipo(atendimento.tipo_atendimento)
  const total = sinais.length
  const progresso = sinais.filter(({ chave }) => sq?.[chave] === true).length
  const pct = total > 0 ? Math.round((progresso / total) * 100) : 0

  const estadoColorClass =
    atendimento.estado === "Fechado" ? "text-success-500" :
    atendimento.estado === "Perdido" ? "text-danger-500" :
    atendimento.ia_pausada ? "text-state-handoff" :
    "text-gold-500"

  const estadoDotClass =
    atendimento.estado === "Fechado" ? "bg-success-500" :
    atendimento.estado === "Perdido" ? "bg-danger-500" :
    atendimento.ia_pausada ? "bg-state-handoff" :
    "bg-gold-500"

  const formaPagamentoLabel = atendimento.forma_pagamento
    ? atendimento.forma_pagamento === "pix"
      ? "PIX"
      : (formatRotulo(atendimento.forma_pagamento) ?? atendimento.forma_pagamento)
    : null

  const linhasLocal = [
    atendimento.bairro,
    atendimento.tipo_local ? (formatRotulo(atendimento.tipo_local) ?? atendimento.tipo_local) : null,
    atendimento.duracao_horas ? `${atendimento.duracao_horas} h` : null,
  ].filter(Boolean) as string[]

  const linhaQuando = [
    atendimento.data_desejada ? formatData(atendimento.data_desejada) : null,
    atendimento.horario_desejado ? atendimento.horario_desejado.slice(0, 5) : null,
  ].filter(Boolean) as string[]

  const pixValidado = atendimento.pix_status === "validado"
  const pixEmRevisao =
    atendimento.pix_status === "em_revisao" ||
    atendimento.pix_status === "aguardando" ||
    atendimento.pix_status === "enviado"

  return (
    <Card className="rounded-lg p-4">
      <div className="mb-4 flex items-center gap-2">
        <ReceiptText size={18} strokeWidth={1.75} className="text-gold-500" />
        <h2 className="text-[15px] font-semibold text-text-primary">Resumo do atendimento</h2>
      </div>

      {/* Hero KPI: valor acordado em destaque, linha de baixo com estado + tipo + quando */}
      <div className="mb-4 overflow-hidden rounded-md border border-ink-300 bg-ink-200">
        <div className="flex flex-wrap items-end justify-between gap-2 px-4 py-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">Valor acordado</p>
            {valorAcordado !== null ? (
              <p className="mt-1 font-serif text-[28px] font-medium leading-none tabular-nums text-gold-500">
                {formatBRL(valorAcordado)}
              </p>
            ) : (
              <p className="mt-1 text-[15px] font-medium text-text-disabled">A combinar</p>
            )}
          </div>
          <span className={cn("inline-flex items-center gap-1.5 rounded-full bg-ink-300 px-3 py-1 text-[12px] font-semibold", estadoColorClass)}>
            <span className={cn("inline-block h-1.5 w-1.5 rounded-full", estadoDotClass)} />
            {estadoLabel[atendimento.estado]}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-px border-t border-ink-300 bg-ink-300">
          <StatTile label="Tipo" icone={<Target size={13} strokeWidth={1.75} className="text-info-500" />}>
            <span className="text-[13px] leading-tight text-text-primary">
              {atendimento.tipo_atendimento
                ? tipoLabel[atendimento.tipo_atendimento]
                : <span className="text-text-disabled">—</span>
              }
            </span>
          </StatTile>
          <StatTile label="Quando" icone={<CalendarClock size={13} strokeWidth={1.75} className="text-text-muted" />}>
            <span className="text-[13px] leading-tight text-text-primary">
              {atendimento.urgencia
                ? urgenciaLabel[atendimento.urgencia]
                : <span className="text-text-disabled">—</span>
              }
            </span>
          </StatTile>
        </div>
      </div>

      {/* Banner de handoff — exibido apenas quando pausada */}
      {atendimento.ia_pausada && (
        <div className="mb-4 rounded-md border-l-4 border-state-handoff bg-state-handoff/10 p-3.5">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={18} strokeWidth={2} className="mt-0.5 shrink-0 text-state-handoff" />
            <div className="min-w-0">
              <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-state-handoff">
                IA pausada · Handoff ativo
              </p>
              <p className="mt-1 text-[14px] leading-snug text-text-primary">
                {motivoExibido(atendimento.motivo_escalada, atendimento.ia_pausada_motivo) ?? "Aguardando decisão"}
                {atendimento.responsavel_atual && (
                  <> · <span className="font-semibold">
                    {formatRotulo(atendimento.responsavel_atual) ?? atendimento.responsavel_atual}
                  </span></>
                )}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Seção: IA */}
      <Secao
        titulo={atendimento.ia_pausada ? "Contexto da IA" : "Resumo da IA"}
        icone={<Sparkles size={14} strokeWidth={1.75} className="text-gold-500" />}
        semDivisor={!atendimento.ia_pausada}
      >
        {atendimento.resumo_operacional ? (
          <p className="text-[14px] leading-relaxed text-text-secondary">
            {atendimento.resumo_operacional}
          </p>
        ) : (
          <p className="text-[14px] leading-relaxed text-text-disabled">
            Aguardando primeira interação da IA
          </p>
        )}
      </Secao>

      {/* Seção: Comercial — pagamento + programas */}
      <Secao
        titulo="Comercial"
        icone={<CreditCard size={14} strokeWidth={1.75} className={pixValidado ? "text-success-500" : "text-text-muted"} />}
      >
        <div className="mb-3">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">Pagamento</p>
          {formaPagamentoLabel ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[15px] font-semibold text-text-primary">{formaPagamentoLabel}</span>
              {atendimento.pix_status && atendimento.pix_status !== "nao_solicitado" && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
                    pixValidado
                      ? "bg-success-500/10 text-success-500"
                      : pixEmRevisao
                        ? "bg-warn-500/10 text-warn-500"
                        : "bg-ink-300 text-text-secondary"
                  )}
                >
                  {pixValidado && <CheckCircle2 size={11} strokeWidth={2.25} />}
                  {formatEnum(String(atendimento.pix_status)) ?? String(atendimento.pix_status)}
                </span>
              )}
              {detalhe.comprovantes_pix[0] && (
                <span className="text-[12px] text-text-muted">
                  {formatDataHora(detalhe.comprovantes_pix[0].created_at)}
                </span>
              )}
            </div>
          ) : (
            <p className="text-[14px] text-text-disabled">Não informado</p>
          )}
        </div>
        <SecaoProgramas programas={detalhe.servicos} />
      </Secao>

      {/* Seção: Agenda / Local */}
      <Secao
        titulo="Agenda / Local"
        icone={<MapPin size={14} strokeWidth={1.75} className="text-info-500" />}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            {atendimento.endereco
              ? <p className="text-[15px] font-medium leading-snug text-text-primary">{atendimento.endereco}</p>
              : <p className="text-[14px] text-text-disabled">Endereço não informado</p>
            }
            <p className="mt-1 text-[13px] text-text-secondary">
              {linhasLocal.length > 0 ? linhasLocal.join(" · ") : <NaoInformado />}
            </p>
            <p className="mt-0.5 text-[13px] text-text-muted">
              {linhaQuando.length > 0 ? linhaQuando.join(" às ") : <NaoInformado />}
            </p>
          </div>
        </div>
      </Secao>

      {/* Seção: Qualificação + Bloqueio (lado a lado em xl) */}
      <Secao
        titulo="Qualificação & Bloqueio"
        icone={<CheckCircle2 size={14} strokeWidth={1.75} className={pct === 100 ? "text-success-500" : "text-text-muted"} />}
      >
        <div className="grid gap-4 xl:grid-cols-2">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-300">
                <div
                  className={cn(
                    "h-2 rounded-full transition-all",
                    pct === 100 ? "bg-success-500" : pct > 0 ? "bg-gold-500" : "bg-ink-400"
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className={cn(
                "text-[13px] font-bold tabular-nums",
                pct === 100 ? "text-success-500" : "text-text-primary"
              )}>{pct}%</span>
            </div>
            <p className={cn(
              "mb-2.5 text-[13px] font-medium",
              pct === 100 ? "text-success-500" : "text-text-muted"
            )}>
              {progresso === 0
                ? "Nenhum item qualificado"
                : progresso === total
                  ? "Totalmente qualificado"
                  : `${progresso} de ${total} qualificados`}
            </p>
            <div className="flex flex-col gap-1">
              {sinais.map(({ chave, rotulo }) => {
                const v = sq?.[chave]
                const estado = v === true ? "sim" : v === false ? "nao" : "pendente"
                return (
                  <span
                    key={chave}
                    className={cn(
                      "flex items-center gap-1.5 text-[13px]",
                      estado === "sim" ? "text-success-500"
                        : estado === "nao" ? "text-danger-500"
                        : "text-text-disabled"
                    )}
                  >
                    {estado === "sim" ? <CheckCircle2 size={14} />
                      : estado === "nao" ? <XCircle size={14} />
                      : <Circle size={14} />}
                    {rotulo}
                  </span>
                )
              })}
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">Bloqueio</p>
            {detalhe.bloqueio ? (
              <>
                <p className="text-[14px] text-text-primary">
                  {formatDataHora(detalhe.bloqueio.inicio)}
                </p>
                <p className="mt-0.5 text-[12px] text-text-muted">
                  {formatRotulo(detalhe.bloqueio.estado) ?? detalhe.bloqueio.estado}
                </p>
                <Link
                  href={`/agenda?bloqueio=${detalhe.bloqueio.id}`}
                  className="mt-1.5 inline-block text-[13px] font-medium text-text-link hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
                >
                  Abrir na agenda →
                </Link>
              </>
            ) : (
              <p className="text-[14px] text-text-disabled">Sem bloqueio vinculado</p>
            )}
          </div>
        </div>
      </Secao>
    </Card>
  )
}

function Secao({
  titulo,
  icone,
  semDivisor,
  children,
}: {
  titulo?: string
  icone?: ReactNode
  semDivisor?: boolean
  children: ReactNode
}) {
  return (
    <div className={cn("mt-4", !semDivisor && "border-t border-ink-300 pt-4")}>
      {titulo && (
        <h3 className="mb-2.5 flex items-center gap-1.5 text-[13px] font-semibold text-text-primary">
          {icone}
          <span>{titulo}</span>
        </h3>
      )}
      {children}
    </div>
  )
}

function StatTile({ label, icone, children }: { label: string; icone?: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-ink-200 px-3 py-2.5">
      <p className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] leading-none text-text-muted">
        {icone}
        <span>{label}</span>
      </p>
      {children}
    </div>
  )
}

function SecaoProgramas({ programas }: { programas: ServicoFechado[] }) {
  const totalProgramas = programas.reduce((sum, p) => sum + p.preco_snapshot, 0)
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        Programas
      </p>
      {programas.length === 0 ? (
        <p className="text-[13px] text-text-disabled">Nenhum programa fechado.</p>
      ) : (
        <div className="space-y-1">
          {programas.map((s) => (
            <div key={s.id} className="flex items-center justify-between">
              <span className="text-[13px] text-text-secondary">
                {s.nome}<span className="text-text-disabled"> · {s.duracao_nome}</span>
              </span>
              <span className="tabular-nums text-[13px] font-medium text-text-primary">
                {formatBRL(s.preco_snapshot)}
              </span>
            </div>
          ))}
          {programas.length > 1 && (
            <div className="mt-1 flex items-center justify-between border-t border-ink-300 pt-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-muted">Total</span>
              <span className="tabular-nums text-[14px] font-semibold text-text-primary">
                {formatBRL(totalProgramas)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
