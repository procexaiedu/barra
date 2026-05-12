"use client"

import type { ReactNode } from "react"
import Link from "next/link"
import { AlertTriangle, CheckCircle2, Circle, MapPin, ReceiptText, XCircle } from "lucide-react"
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

  return (
    <Card className="rounded-lg p-4">
      <div className="mb-3 flex items-center gap-2">
        <ReceiptText size={16} strokeWidth={1.5} className="text-text-muted" />
        <h2 className="text-sm font-semibold text-text-primary">Resumo do atendimento</h2>
      </div>

      {/* Stat tiles: 4 métricas em strip scanável — não usa label:value */}
      <div className="mb-3 grid grid-cols-2 gap-px overflow-hidden rounded-md bg-ink-400 sm:grid-cols-4">
        <StatTile label="Estado">
          <span className={cn("text-[13px] font-semibold leading-tight", estadoColorClass)}>
            {estadoLabel[atendimento.estado]}
          </span>
        </StatTile>
        <StatTile label="Valor acordado">
          {valorAcordado !== null
            ? <span className="text-[16px] font-bold leading-none tabular-nums text-text-primary">{formatBRL(valorAcordado)}</span>
            : <span className="text-[13px] text-text-disabled">—</span>
          }
        </StatTile>
        <StatTile label="Tipo">
          <span className="text-[13px] leading-tight text-text-primary">
            {atendimento.tipo_atendimento
              ? tipoLabel[atendimento.tipo_atendimento]
              : <span className="text-text-disabled">—</span>
            }
          </span>
        </StatTile>
        <StatTile label="Quando">
          <span className="text-[13px] leading-tight text-text-primary">
            {atendimento.urgencia
              ? urgenciaLabel[atendimento.urgencia]
              : <span className="text-text-disabled">—</span>
            }
          </span>
        </StatTile>
      </div>

      {/* Banner de handoff — exibido apenas quando pausada */}
      {atendimento.ia_pausada && (
        <div className="mb-3 rounded-md bg-state-handoff/5 p-3 ring-1 ring-state-handoff/20">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={14} strokeWidth={2} className="mt-0.5 shrink-0 text-state-handoff" />
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-state-handoff">
                IA pausada · Handoff ativo
              </p>
              <p className="mt-0.5 text-[13px] text-text-secondary">
                {motivoExibido(atendimento.motivo_escalada, atendimento.ia_pausada_motivo) ?? "Aguardando decisão"}
                {atendimento.responsavel_atual && (
                  <> · <span className="font-medium text-text-primary">
                    {formatRotulo(atendimento.responsavel_atual) ?? atendimento.responsavel_atual}
                  </span></>
                )}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Campo 'Próxima Ação' obsoleto no MVP (task 0855ee14) */}

      {/* Resumo da IA — prosa, não linha de tabela */}
      {atendimento.resumo_operacional && (
        <div className="mb-3">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            {atendimento.ia_pausada ? "Contexto" : "Resumo da IA"}
          </p>
          <p className="text-[13px] leading-relaxed text-text-secondary">
            {atendimento.resumo_operacional}
          </p>
        </div>
      )}

      {/* Logística + Pagamento — bloco de endereço à esquerda, pgto à direita */}
      <div className="mb-3 grid gap-3 xl:grid-cols-[1fr_auto]">
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Agenda / Local
          </p>
          <div className="flex items-start gap-1.5">
            <MapPin
              size={13}
              strokeWidth={1.5}
              className={cn("mt-0.5 shrink-0", atendimento.endereco ? "text-text-muted" : "text-text-disabled")}
            />
            <div className="min-w-0">
              {atendimento.endereco
                ? <p className="text-[13px] font-medium leading-snug text-text-primary">{atendimento.endereco}</p>
                : <p className="text-[13px] text-text-disabled">Endereço não informado</p>
              }
              {(atendimento.bairro || atendimento.tipo_local || atendimento.duracao_horas) && (
                <p className="mt-0.5 text-[12px] text-text-muted">
                  {[
                    atendimento.bairro,
                    atendimento.tipo_local ? (formatRotulo(atendimento.tipo_local) ?? atendimento.tipo_local) : null,
                    atendimento.duracao_horas ? `${atendimento.duracao_horas} h` : null,
                  ].filter(Boolean).join(" · ")}
                </p>
              )}
              {(atendimento.data_desejada || atendimento.horario_desejado) && (
                <p className="mt-0.5 text-[12px] text-text-muted">
                  {[
                    atendimento.data_desejada ? formatData(atendimento.data_desejada) : null,
                    atendimento.horario_desejado ? atendimento.horario_desejado.slice(0, 5) : null,
                  ].filter(Boolean).join(" às ")}
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="shrink-0 xl:text-right">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">Pagamento</p>
          <p className="mt-0.5 text-[13px] font-medium text-text-primary">
            {atendimento.forma_pagamento
              ? atendimento.forma_pagamento === "pix" ? "PIX" : (formatRotulo(atendimento.forma_pagamento) ?? atendimento.forma_pagamento)
              : <span className="font-normal text-text-disabled">Não informado</span>
            }
          </p>
          {atendimento.pix_status && atendimento.pix_status !== "nao_solicitado" && (
            <p className="mt-0.5 text-[11px] text-text-muted">
              {formatEnum(String(atendimento.pix_status)) ?? String(atendimento.pix_status)}
              {detalhe.comprovantes_pix[0] && <> · {formatDataHora(detalhe.comprovantes_pix[0].created_at)}</>}
            </p>
          )}
        </div>
      </div>

      <SecaoProgramas programas={detalhe.servicos} />

      <div className="mt-3 grid gap-4 border-t border-ink-300 pt-3 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Qualificação
          </h3>
          <div className="mb-1.5 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-ink-300">
              <div
                className="h-1.5 rounded-full bg-success-500 transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-xs font-semibold tabular-nums text-text-primary">{pct}%</span>
          </div>
          <p className="mb-2 text-[12px] text-text-muted">
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
                    "flex items-center gap-1.5 text-[12px]",
                    estado === "sim" ? "text-success-500"
                      : estado === "nao" ? "text-danger-500"
                      : "text-text-disabled"
                  )}
                >
                  {estado === "sim" ? <CheckCircle2 size={13} />
                    : estado === "nao" ? <XCircle size={13} />
                    : <Circle size={13} />}
                  {rotulo}
                </span>
              )
            })}
          </div>
        </div>

        {detalhe.bloqueio && (
          <div>
            <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">Bloqueio</h3>
            <p className="text-[13px] text-text-secondary">
              {formatDataHora(detalhe.bloqueio.inicio)} · {formatRotulo(detalhe.bloqueio.estado) ?? detalhe.bloqueio.estado}
            </p>
            <Link
              href={`/agenda?bloqueio=${detalhe.bloqueio.id}`}
              className="mt-1 inline-block text-[13px] text-text-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
            >
              Abrir na agenda
            </Link>
          </div>
        )}
      </div>
    </Card>
  )
}

function StatTile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="bg-ink-200 px-3 py-2.5">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] leading-none text-text-muted">
        {label}
      </p>
      {children}
    </div>
  )
}

function SecaoProgramas({ programas }: { programas: ServicoFechado[] }) {
  const totalProgramas = programas.reduce((sum, p) => sum + p.preco_snapshot, 0)
  return (
    <div className="border-t border-ink-300 pt-3">
      <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        Programas
      </h3>
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
              <span className="tabular-nums text-[14px] font-bold text-text-primary">
                {formatBRL(totalProgramas)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
