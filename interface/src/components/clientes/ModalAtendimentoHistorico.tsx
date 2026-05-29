"use client"

import { useCallback, useEffect, useState } from "react"
import { X } from "lucide-react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatBRL, formatData, formatRotulo, formatTelefone } from "@/lib/formatters"
import { FeticheValor } from "@/components/comum/FeticheValor"
import { badgeForEstado, estadoAtendimentoLabel, motivoPerdaLabel } from "@/components/clientes/utils"
import { HistoricoMensagens } from "@/components/atendimentos/HistoricoMensagens"
import type { AtendimentoDetalheResponse } from "@/tipos/atendimentos"

const tipoLabel: Record<string, string> = { interno: "Interno", externo: "Externo" }
const urgenciaLabel: Record<string, string> = {
  imediato: "Imediato",
  agendado: "Agendado",
  indefinido: "Indefinido",
  estimado: "Estimado",
}

function Campo({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
      </p>
      <p className="text-sm text-text-primary">{value}</p>
    </div>
  )
}

function SecaoHeader({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
      {children}
    </p>
  )
}

export function ModalAtendimentoHistorico({
  atendimentoId,
  onClose,
}: {
  atendimentoId: string | null
  onClose: () => void
}) {
  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [erro, setErro] = useState<string | null>(null)

  const carregar = useCallback(async (id: string) => {
    setStatus("loading")
    setDetalhe(null)
    setErro(null)
    try {
      const res = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`)
      setDetalhe({
        ...res,
        mensagens: Array.isArray(res.mensagens) ? res.mensagens : [],
      })
      setStatus("success")
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao carregar")
      setStatus("error")
    }
  }, [])

  useEffect(() => {
    if (!atendimentoId) return
    void Promise.resolve().then(() => carregar(atendimentoId))
  }, [atendimentoId, carregar])

  const at = detalhe?.atendimento
  const isFechado = at?.estado === "Fechado"
  const isPerdido = at?.estado === "Perdido"
  const temLocalizacao = Boolean(at?.endereco || at?.bairro || at?.tipo_local || at?.forma_pagamento)
  const totalServicos = detalhe?.servicos.reduce((acc, sv) => acc + sv.preco_snapshot, 0) ?? 0

  return (
    <Dialog open={!!atendimentoId} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex h-[88vh] max-w-2xl flex-col overflow-hidden bg-surface p-0">
        <DialogTitle className="sr-only">Detalhe do atendimento</DialogTitle>

        {/* Header */}
        <div className="flex flex-none items-center justify-between border-b border-border bg-surface px-5 py-3">
          <span className="text-sm font-semibold text-text-primary">
            {detalhe
              ? `${detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)} · #${at?.numero_curto}`
              : "Atendimento"}
          </span>
          <div className="flex items-center gap-2">
            {at && (
              <Badge variant={badgeForEstado(at.estado)}>
                {estadoAtendimentoLabel[at.estado]}
              </Badge>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Fechar"
              className="rounded-md p-1 text-text-muted hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors"
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="scroll-thin flex-1 overflow-y-auto p-5 space-y-5">

          {/* Carregando */}
          {status === "loading" && (
            <div className="space-y-5">
              <div className="rounded-lg border border-border bg-card p-4">
                <Skeleton className="mb-3 h-2.5 w-20" />
                <div className="grid grid-cols-2 gap-4">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="space-y-1.5">
                      <Skeleton className="h-2 w-16" />
                      <Skeleton className="h-4 w-28" />
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card p-4">
                <Skeleton className="mb-3 h-2.5 w-24" />
                <div className="grid grid-cols-2 gap-4">
                  {[0, 1].map((i) => (
                    <div key={i} className="space-y-1.5">
                      <Skeleton className="h-2 w-16" />
                      <Skeleton className="h-4 w-28" />
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card p-4">
                <Skeleton className="mb-3 h-2.5 w-16" />
                <Skeleton className="h-7 w-32" />
              </div>
            </div>
          )}

          {/* Erro */}
          {status === "error" && (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <p className="text-sm text-text-muted">
                {erro ?? "Erro ao carregar atendimento."}
              </p>
              <button
                type="button"
                onClick={() => atendimentoId && carregar(atendimentoId)}
                className="rounded-md bg-surface-hover px-4 py-2 text-sm font-medium text-text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors"
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* Conteúdo */}
          {status === "success" && detalhe && at && (
            <>
              {/* Identificação */}
              <section className="rounded-lg border border-border bg-card p-4">
                <SecaoHeader>Identificação</SecaoHeader>
                <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                  <Campo label="Abertura" value={formatData(at.created_at)} />
                  <Campo label="Modelo" value={detalhe.modelo.nome} />
                  <Campo
                    label="Tipo"
                    value={at.tipo_atendimento
                      ? (tipoLabel[at.tipo_atendimento] ?? at.tipo_atendimento)
                      : "—"}
                  />
                  <Campo
                    label="Urgência"
                    value={at.urgencia
                      ? (urgenciaLabel[at.urgencia] ?? at.urgencia)
                      : "—"}
                  />
                </div>
              </section>

              {/* Localização & Serviço */}
              {temLocalizacao && (
                <section className="rounded-lg border border-border bg-card p-4">
                  <SecaoHeader>Localização & Serviço</SecaoHeader>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                    <Campo label="Endereço" value={at.endereco ?? "—"} />
                    <Campo label="Bairro" value={at.bairro ?? "—"} />
                    <Campo label="Tipo de local" value={formatRotulo(at.tipo_local) ?? "—"} />
                    <Campo label="Pagamento" value={formatRotulo(at.forma_pagamento) ?? "—"} />
                  </div>
                </section>
              )}

              {/* Financeiro */}
              <section className="rounded-lg border border-border bg-card p-4">
                <SecaoHeader>Financeiro</SecaoHeader>
                <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                  <Campo
                    label="Valor acordado"
                    value={at.valor_acordado !== null && at.valor_acordado !== undefined
                      ? formatBRL(Number(at.valor_acordado))
                      : "—"}
                  />
                  <div className="min-w-0">
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                      Valor final
                    </p>
                    <p className={
                      isFechado && at.valor_final !== null && at.valor_final !== undefined
                        ? "text-sm font-semibold text-state-won"
                        : "text-sm text-text-primary"
                    }>
                      {at.valor_final !== null && at.valor_final !== undefined
                        ? formatBRL(Number(at.valor_final))
                        : "—"}
                    </p>
                  </div>
                </div>
              </section>

              {/* Resultado */}
              {(isFechado || isPerdido) && (
                <section className="rounded-lg border border-border bg-card p-4">
                  <SecaoHeader>Resultado</SecaoHeader>
                  {isFechado && (
                    <div className="flex items-center gap-3">
                      <Badge variant="closed">{estadoAtendimentoLabel[at.estado]}</Badge>
                      {at.valor_final !== null && at.valor_final !== undefined && (
                        <span className="text-base font-semibold text-state-won tabular-nums">
                          {formatBRL(Number(at.valor_final))}
                        </span>
                      )}
                    </div>
                  )}
                  {isPerdido && (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="lost">{estadoAtendimentoLabel[at.estado]}</Badge>
                        {at.motivo_perda && (
                          <span className="text-sm text-text-secondary">
                            {motivoPerdaLabel[at.motivo_perda]}
                          </span>
                        )}
                      </div>
                      {at.motivo_perda === "outro" && at.motivo_perda_obs && (
                        <p className="text-xs text-text-muted">{at.motivo_perda_obs}</p>
                      )}
                    </div>
                  )}
                </section>
              )}

              {/* Serviços */}
              {detalhe.servicos.length > 0 && (
                <section className="rounded-lg border border-border bg-card p-4">
                  <SecaoHeader>Serviços</SecaoHeader>
                  <ul className="space-y-2">
                    {detalhe.servicos.map((sv) => (
                      <li key={sv.id} className="flex items-center justify-between text-sm">
                        <span className="text-text-secondary">{sv.nome}</span>
                        <span className="font-medium tabular-nums text-text-primary">
                          {formatBRL(sv.preco_snapshot)}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {detalhe.servicos.length > 1 && (
                    <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-sm">
                      <span className="text-text-muted">Total</span>
                      <span className="font-semibold tabular-nums text-text-primary">
                        {formatBRL(totalServicos)}
                      </span>
                    </div>
                  )}
                </section>
              )}

              {/* Fetiches (composição — preço incluso ou extra) */}
              {(detalhe.fetiches ?? []).length > 0 && (
                <section className="rounded-lg border border-border bg-card p-4">
                  <SecaoHeader>Fetiches</SecaoHeader>
                  <ul className="space-y-2">
                    {detalhe.fetiches.map((f) => (
                      <li key={f.id} className="flex items-center justify-between gap-3 text-sm">
                        <span className="text-text-secondary">{f.nome}</span>
                        <FeticheValor preco={f.preco_snapshot} />
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Resumo (campo 'Próxima Ação' obsoleto no MVP — task 0855ee14) */}
              {at.resumo_operacional && (
                <section className="rounded-lg border border-border bg-card p-4">
                  <SecaoHeader>Contexto operacional</SecaoHeader>
                  <div>
                    <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                      Resumo
                    </p>
                    <p className="text-sm text-text-secondary">{at.resumo_operacional}</p>
                  </div>
                </section>
              )}

              {/* Conversa */}
              <section className="rounded-lg border border-border bg-card p-4">
                <SecaoHeader>Conversa</SecaoHeader>
                <HistoricoMensagens mensagens={detalhe.mensagens} />
              </section>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
