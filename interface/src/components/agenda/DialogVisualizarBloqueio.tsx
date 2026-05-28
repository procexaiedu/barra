"use client"

import { useCallback, useEffect, useState } from "react"
import { X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { formatBRL, formatData } from "@/lib/formatters"
import type { AtendimentoDetalheResponse } from "@/tipos/atendimentos"
import type { BloqueioAgenda, EstadoBloqueio } from "@/tipos/agenda"

const estadoBadgeVariant: Record<EstadoBloqueio, "active" | "paused" | "closed" | "lost"> = {
  bloqueado: "paused",
  em_atendimento: "active",
  concluido: "closed",
  cancelado: "paused",
}

const estadoLabel: Record<EstadoBloqueio, string> = {
  bloqueado: "Bloqueado",
  em_atendimento: "Em atendimento",
  concluido: "Concluído",
  cancelado: "Cancelado",
}

const tipoLabel: Record<string, string> = { interno: "Interno", externo: "Externo" }

function calcDuracaoMin(inicio: string, fim: string): number {
  const [h1, m1] = inicio.split(":").map(Number)
  const [h2, m2] = fim === "24:00" ? [24, 0] : fim.split(":").map(Number)
  let total = h2 * 60 + m2 - (h1 * 60 + m1)
  if (total <= 0) total += 24 * 60
  return total
}

function duracaoLabel(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, "0")}`
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

function formatValor(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—"
  const n = typeof v === "string" ? parseFloat(v) : v
  return Number.isNaN(n) ? "—" : formatBRL(n)
}

export function DialogVisualizarBloqueio({
  bloqueio,
  open,
  onOpenChange,
  onEditar,
}: {
  bloqueio: BloqueioAgenda
  open: boolean
  onOpenChange: (v: boolean) => void
  onEditar: () => void
}) {
  const atendimento = bloqueio.atendimento
  const atendimentoId = bloqueio.atendimento_id
  const ehAgendamento = Boolean(atendimentoId)

  const inicioData = bloqueio.inicio.slice(0, 10)
  const fimData = bloqueio.fim.slice(0, 10)
  const inicioHora = bloqueio.inicio.slice(11, 16)
  const fimHora = fimData > inicioData && bloqueio.fim.slice(11, 16) === "00:00"
    ? "24:00"
    : bloqueio.fim.slice(11, 16)
  const overnight = fimHora !== "24:00" && fimHora < inicioHora
  const duracaoMin = calcDuracaoMin(inicioHora, fimHora)

  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [statusDetalhe, setStatusDetalhe] = useState<"idle" | "loading" | "success" | "error">("idle")

  const carregar = useCallback(async (id: string) => {
    setStatusDetalhe("loading")
    setDetalhe(null)
    try {
      const data = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`)
      setDetalhe(data)
      setStatusDetalhe("success")
    } catch {
      setStatusDetalhe("error")
    }
  }, [])

  useEffect(() => {
    if (!open || !atendimentoId) return
    void Promise.resolve().then(() => carregar(atendimentoId))
  }, [open, atendimentoId, carregar])

  const titulo = ehAgendamento ? "Detalhe do agendamento" : "Detalhe do bloqueio"

  const programa = detalhe?.servicos.length
    ? detalhe.servicos.map((s) => s.nome).join(", ")
    : null
  const resumo = detalhe?.atendimento.resumo_operacional ?? null
  const proximaAcao = detalhe?.atendimento.proxima_acao_esperada ?? null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[min(96vw,72rem)] max-h-[92vh] flex-col overflow-hidden rounded-lg border border-border-strong bg-popover text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <DialogTitle className="sr-only">{titulo}</DialogTitle>

        {/* Header */}
        <div className="flex flex-none items-start justify-between gap-4 border-b border-border px-8 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5">
              <h2 className="text-lg font-semibold leading-tight text-text-primary">
                {titulo}
              </h2>
              <Badge variant={estadoBadgeVariant[bloqueio.estado]}>
                {estadoLabel[bloqueio.estado]}
              </Badge>
            </div>
            {bloqueio.modelo_nome && (
              <p className="mt-1 text-sm font-medium text-text-secondary">
                {bloqueio.modelo_nome}
              </p>
            )}
            {atendimento && (
              <p className="mt-0.5 font-mono text-xs text-text-muted">
                #{atendimento.numero_curto} · {atendimento.cliente_nome ?? atendimento.cliente_telefone_formatado}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-md p-1 text-text-muted hover:bg-muted hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
            aria-label="Fechar"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        {/* Body */}
        <div className="scroll-thin flex-1 overflow-y-auto px-8 py-6">
          {/* Hero: data + horário + duração + modelo (full-width) */}
          <section className="mb-6 overflow-hidden rounded-lg border border-border bg-muted">
            <div className="grid grid-cols-1 gap-px bg-border md:grid-cols-4">
              <div className="bg-muted px-5 py-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Data
                </p>
                <p className="mt-1 text-base font-medium text-text-primary">
                  {formatData(bloqueio.inicio)}
                </p>
              </div>
              <div className="bg-muted px-5 py-4 md:col-span-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Horário
                </p>
                <p className="mt-1 font-mono text-[34px] font-medium leading-none tabular-nums text-text-brand">
                  {inicioHora}<span className="px-1 text-text-muted">–</span>{fimHora}
                  {overnight && (
                    <span className="ml-2 align-middle font-sans text-xs font-normal text-text-muted">(próx. dia)</span>
                  )}
                </p>
              </div>
              <div className="bg-muted px-5 py-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Duração
                </p>
                <p className="mt-1 text-base font-medium text-text-primary">
                  {duracaoLabel(duracaoMin)}
                </p>
              </div>
            </div>
            {bloqueio.modelo_nome && (
              <div className="border-t border-border bg-muted px-5 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  Modelo
                </p>
                <p className="mt-0.5 text-sm font-medium text-text-primary">
                  {bloqueio.modelo_nome}
                </p>
              </div>
            )}
          </section>

          {/* Grid principal */}
          <div className={cn(
            "grid gap-6",
            atendimento ? "lg:grid-cols-2" : "grid-cols-1"
          )}>
            {/* Coluna esquerda: Atendimento vinculado */}
            {atendimento && (
              <section className="rounded-lg border border-border bg-surface p-5">
                <SecaoHeader>Atendimento vinculado</SecaoHeader>
                <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                  <Campo label="Número" value={`#${atendimento.numero_curto}`} />
                  <Campo
                    label="Cliente"
                    value={atendimento.cliente_nome ?? atendimento.cliente_telefone_formatado}
                  />
                  <Campo label="Telefone" value={atendimento.cliente_telefone_formatado} />
                  <Campo
                    label="Tipo"
                    value={atendimento.tipo_atendimento
                      ? (tipoLabel[atendimento.tipo_atendimento] ?? atendimento.tipo_atendimento)
                      : "—"}
                  />
                  <Campo
                    label="Valor acordado"
                    value={formatValor(atendimento.valor_acordado)}
                  />
                  <Campo
                    label="Endereço"
                    value={[atendimento.endereco, atendimento.bairro].filter(Boolean).join(", ") || "—"}
                  />
                  <Campo
                    label="Data desejada"
                    value={atendimento.data_desejada
                      ? formatData(atendimento.data_desejada)
                      : "—"}
                  />
                  <Campo
                    label="Horário desejado"
                    value={atendimento.horario_desejado
                      ? String(atendimento.horario_desejado).slice(0, 5)
                      : "—"}
                  />
                </div>
              </section>
            )}

            {/* Coluna direita: Programa & Resumo + Observação */}
            <div className="space-y-6">
              {atendimentoId && (
                <section className="rounded-lg border border-border bg-surface p-5">
                  <SecaoHeader>Programa & Resumo</SecaoHeader>
                  {statusDetalhe === "loading" && (
                    <div className="space-y-3">
                      <Skeleton className="h-4 w-40" />
                      <Skeleton className="h-4 w-full" />
                      <Skeleton className="h-4 w-3/4" />
                    </div>
                  )}
                  {statusDetalhe === "success" && (
                    <div className="space-y-4">
                      <div>
                        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                          Programa
                        </p>
                        <p className="text-sm text-text-primary">{programa ?? "—"}</p>
                      </div>
                      {resumo && (
                        <div>
                          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                            Resumo operacional
                          </p>
                          <p className="text-sm leading-relaxed text-text-secondary">{resumo}</p>
                        </div>
                      )}
                      {proximaAcao && (
                        <div>
                          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                            Próxima ação esperada
                          </p>
                          <p className="text-sm leading-relaxed text-text-secondary">{proximaAcao}</p>
                        </div>
                      )}
                      {!resumo && !proximaAcao && !programa && (
                        <p className="text-sm text-text-muted">Sem informações registradas.</p>
                      )}
                    </div>
                  )}
                  {statusDetalhe === "error" && (
                    <p className="text-sm text-text-muted">
                      Não foi possível carregar programa e resumo.
                    </p>
                  )}
                </section>
              )}

              <section className="rounded-lg border border-border bg-surface p-5">
                <SecaoHeader>Observação</SecaoHeader>
                <p className="text-sm leading-relaxed text-text-primary">
                  {bloqueio.observacao ?? "—"}
                </p>
              </section>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-none items-center justify-end gap-2 border-t border-border px-8 py-4">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
          <Button variant="primary" onClick={onEditar}>
            Editar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
