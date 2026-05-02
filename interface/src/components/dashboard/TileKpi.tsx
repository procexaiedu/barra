"use client"

import type { ReactNode } from "react"
import { Info, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

interface Props {
  label: string
  valor: ReactNode
  valorClassName?: string
  linhaAuxiliar?: ReactNode
  tendencia?: ReactNode
  rangeComparacao?: string | null
  icone?: LucideIcon
  iconeClassName?: string
  tooltip?: ReactNode
}

export function TileKpi({
  label,
  valor,
  valorClassName,
  linhaAuxiliar,
  tendencia,
  rangeComparacao,
  icone: Icone,
  iconeClassName,
  tooltip,
}: Props) {
  const mostrarFooter = Boolean(tendencia || rangeComparacao)

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-card p-6 ring-1 ring-foreground/10">
      <header className="flex items-center gap-2">
        {Icone ? (
          <Icone
            size={14}
            strokeWidth={1.75}
            aria-hidden
            className={cn("text-text-muted", iconeClassName)}
          />
        ) : null}
        <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
          {label}
        </span>
        {tooltip ? (
          <Tooltip>
            <TooltipTrigger
              type="button"
              aria-label={`Sobre ${label}`}
              className="inline-flex items-center text-text-muted/60 transition-colors hover:text-text-primary focus-visible:text-text-primary focus-visible:outline-none"
            >
              <Info size={12} strokeWidth={1.75} aria-hidden />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[260px] text-left leading-snug">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </header>

      <p
        className={cn(
          "font-sans text-[40px] font-medium leading-[48px] text-text-primary tabular-nums",
          valorClassName
        )}
      >
        {valor}
      </p>

      {linhaAuxiliar ? (
        <p className="text-[13px] text-text-muted">{linhaAuxiliar}</p>
      ) : null}

      {mostrarFooter ? (
        <footer className="mt-auto flex items-center justify-between gap-2 pt-1">
          <span className="inline-flex">{tendencia}</span>
          {rangeComparacao ? (
            <span className="font-mono text-[11px] text-text-muted">vs {rangeComparacao}</span>
          ) : null}
        </footer>
      ) : null}
    </div>
  )
}
