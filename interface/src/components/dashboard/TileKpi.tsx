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
  onClick?: () => void
  ariaLabel?: string
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
  onClick,
  ariaLabel,
}: Props) {
  const mostrarFooter = Boolean(tendencia || rangeComparacao)
  const interativo = Boolean(onClick)

  const conteudo = (
    <>
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
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.stopPropagation()
                }
              }}
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
            <span className="font-mono text-[11px] text-text-muted">Comparado com: {rangeComparacao}</span>
          ) : null}
        </footer>
      ) : null}
    </>
  )

  const baseClass =
    "flex flex-col gap-3 rounded-lg bg-card p-6 ring-1 ring-foreground/10 text-left"

  if (interativo) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={ariaLabel}
        onClick={onClick}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            onClick?.()
          }
        }}
        className={cn(
          baseClass,
          "cursor-pointer transition-colors hover:bg-ink-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        )}
      >
        {conteudo}
      </div>
    )
  }

  return <div className={baseClass}>{conteudo}</div>
}
