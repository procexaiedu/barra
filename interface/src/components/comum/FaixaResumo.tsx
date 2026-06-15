"use client"

import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

export interface ResumoKpi {
  label: string
  valor: string
  /** Destaca o valor em verde (ex: faturamento). */
  destaque?: boolean
}

/**
 * Faixa de resumo colapsável reutilizável (Atendimentos, Clientes, Modelos):
 * uma linha de KPIs sempre visível + um detalhe expansível opcional. Reflete o
 * recorte de filtros da tela. Puramente apresentacional — quem usa cuida de
 * loading/erro (ver `SkeletonFaixaResumo`).
 */
export function FaixaResumo({
  rotulo,
  icone,
  kpis,
  children,
}: {
  rotulo: string
  icone: ReactNode
  kpis: ResumoKpi[]
  children?: ReactNode
}) {
  const [aberto, setAberto] = useState(false)
  const temDetalhe = Boolean(children)

  return (
    <div className="rounded-lg bg-card ring-1 ring-foreground/10">
      <button
        type="button"
        onClick={() => temDetalhe && setAberto((v) => !v)}
        aria-expanded={temDetalhe ? aberto : undefined}
        className={cn(
          "flex w-full flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-left",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
          temDetalhe ? "cursor-pointer transition-colors hover:bg-accent" : "cursor-default"
        )}
      >
        <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
          {icone}
          {rotulo}
        </span>
        {kpis.map((k) => (
          <span key={k.label} className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-text-muted">{k.label}</span>
            <span
              className={cn(
                "font-mono text-sm font-semibold tabular-nums",
                k.destaque ? "text-success-500" : "text-text-primary"
              )}
            >
              {k.valor}
            </span>
          </span>
        ))}
        {temDetalhe ? (
          <ChevronDown
            size={16}
            strokeWidth={1.5}
            aria-hidden
            className={cn("ml-auto text-text-muted transition-transform", aberto && "rotate-180")}
          />
        ) : null}
      </button>

      {aberto && temDetalhe ? (
        <div className="border-t border-border/60 px-4 py-3">{children}</div>
      ) : null}
    </div>
  )
}

export function SkeletonFaixaResumo() {
  return (
    <div
      aria-busy="true"
      className="h-[46px] animate-pulse rounded-lg bg-card ring-1 ring-foreground/10"
    />
  )
}
