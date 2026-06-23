"use client"

import type { ReactNode } from "react"
import { SlidersHorizontal } from "lucide-react"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

/** Container "Filtros" (botão compacto + Popover) que esconde filtros secundários
 *  para a barra primária não virar um muro de dropdowns. Generaliza o padrão de
 *  Atendimentos. Cada surface compõe suas próprias linhas via `children`. */
export function PainelFiltros({
  ativos,
  onLimpar,
  children,
}: {
  /** Quantidade de filtros ativos (badge). */
  ativos: number
  /** Ação "Limpar filtros" — só aparece quando há filtros ativos. */
  onLimpar?: () => void
  children: ReactNode
}) {
  return (
    <Popover>
      <PopoverTrigger
        data-slot="filtros-secundarios-trigger"
        className="relative inline-flex h-9 items-center gap-1.5 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <SlidersHorizontal size={15} strokeWidth={1.5} className="text-text-muted" />
        Filtros
        {ativos > 0 && (
          <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-gold-500 px-1 text-[11px] font-semibold tabular-nums text-on-brand">
            {ativos}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent
        data-slot="filtros-secundarios-content"
        align="end"
        className="flex w-[240px] flex-col gap-3"
      >
        {children}
        {ativos > 0 && onLimpar && (
          <button
            type="button"
            onClick={onLimpar}
            className="self-start text-xs font-medium text-text-link hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            Limpar filtros
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}
