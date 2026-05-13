"use client"

import Link from "next/link"
import { ArrowUpRight, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import { tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"
import { cn } from "@/lib/utils"
import type {
  AtendimentoResumoPix,
  ClienteResumoPix,
  ModeloResumoPix,
} from "@/tipos/pix"
import {
  badgeForEstadoAtendimento,
  estadoAtendimentoLabel,
} from "./utils"

export function ModalAtendimentoPix({
  open,
  onOpenChange,
  atendimento,
  cliente,
  modelo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  atendimento: AtendimentoResumoPix | null
  cliente?: ClienteResumoPix | null
  modelo?: ModeloResumoPix | null
}) {
  const clienteLabel = cliente
    ? cliente.nome ?? formatTelefone(cliente.telefone)
    : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-[min(96vw,56rem)] max-h-[88vh] flex-col overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        {/* Header */}
        <div className="flex flex-shrink-0 items-start justify-between gap-4 border-b border-border px-8 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <DialogTitle className="text-lg font-semibold text-text-primary">
                Atendimento vinculado
              </DialogTitle>
              {atendimento && (
                <Badge variant={badgeForEstadoAtendimento(atendimento.estado)}>
                  {estadoAtendimentoLabel[atendimento.estado] ?? atendimento.estado}
                </Badge>
              )}
            </div>
            {atendimento && (
              <p className="mt-1 font-mono text-xs text-text-muted">
                #{atendimento.numero_curto}
              </p>
            )}
          </div>
          <DialogClose
            render={
              <Button variant="ghost" size="icon" aria-label="Fechar">
                <X size={18} strokeWidth={1.5} />
              </Button>
            }
          />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {atendimento === null ? (
            <p className="text-sm text-text-muted">
              Pix sem atendimento vinculado.
            </p>
          ) : (
            <div className="space-y-5">
              {/* Hero KPIs */}
              <div className="grid grid-cols-3 gap-3">
                <KpiBlock label="Tipo">
                  {atendimento.tipo_atendimento ? (
                    <span className="text-text-primary">
                      {tipoLabel[atendimento.tipo_atendimento]}
                    </span>
                  ) : (
                    <Vazio />
                  )}
                </KpiBlock>
                <KpiBlock label="Urgência">
                  {atendimento.urgencia ? (
                    <span className="text-text-primary">
                      {urgenciaLabel[atendimento.urgencia]}
                    </span>
                  ) : (
                    <Vazio />
                  )}
                </KpiBlock>
                <KpiBlock label="Valor acordado">
                  {atendimento.valor_acordado !== null ? (
                    <span className="font-semibold text-text-primary">
                      {formatBRL(atendimento.valor_acordado)}
                    </span>
                  ) : (
                    <Vazio />
                  )}
                </KpiBlock>
              </div>

              {/* Próxima ação */}
              {atendimento.proxima_acao_esperada && (
                <section className="rounded-lg border border-state-handoff/40 bg-state-handoff/10 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-state-handoff">
                    Próxima ação esperada
                  </p>
                  <p className="mt-1 text-sm text-text-primary">
                    {atendimento.proxima_acao_esperada}
                  </p>
                </section>
              )}

              {/* Cliente / Modelo */}
              {(clienteLabel || modelo) && (
                <div className="grid grid-cols-2 gap-3">
                  {clienteLabel && (
                    <InfoBlock label="Cliente">{clienteLabel}</InfoBlock>
                  )}
                  {modelo && <InfoBlock label="Modelo">{modelo.nome}</InfoBlock>}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {atendimento && (
          <div className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-border px-8 py-4">
            <Link
              href={`/atendimentos?id=${atendimento.id}`}
              className={cn(buttonVariants({ variant: "primary" }), "gap-1.5")}
            >
              Abrir nos Atendimentos
              <ArrowUpRight size={14} strokeWidth={1.8} />
            </Link>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function KpiBlock({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      <p className="mt-1.5 text-base leading-tight">{children}</p>
    </div>
  )
}

function InfoBlock({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      <p className="mt-1 text-sm text-text-primary">{children}</p>
    </div>
  )
}

function Vazio() {
  return <span className="text-text-muted">—</span>
}
