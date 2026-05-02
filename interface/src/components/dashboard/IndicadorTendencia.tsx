"use client"

import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import { cn } from "@/lib/utils"
import { calcularDeltaPercentual, formatDeltaPercentual } from "./utils"

type Polaridade = "direta" | "invertida"

interface Props {
  atual: number
  anterior: number
  unidade: "%" | "pp"
  polaridade: Polaridade
  base?: "valor" | "pp"
}

export function IndicadorTendencia({ atual, anterior, unidade, polaridade }: Props) {
  if (atual === 0 && anterior === 0) {
    return (
      <span className="inline-flex items-center text-xs font-medium text-text-muted">—</span>
    )
  }

  if (anterior === 0) {
    return (
      <span className="inline-flex items-center text-xs font-medium text-text-muted">—</span>
    )
  }

  const delta = unidade === "pp" ? atual - anterior : calcularDeltaPercentual(atual, anterior)
  const absDelta = Math.abs(delta)
  const zeroEfetivo = absDelta < 0.05

  let cor = "text-text-muted"
  let bg = ""
  let Icone = Minus

  if (zeroEfetivo) {
    Icone = Minus
    cor = "text-text-muted"
    bg = ""
  } else if (delta > 0) {
    Icone = ArrowUp
    cor = polaridade === "direta" ? "text-success-500" : "text-danger-500"
    bg = polaridade === "direta" ? "bg-success-500/10" : "bg-danger-500/10"
  } else {
    Icone = ArrowDown
    cor = polaridade === "direta" ? "text-danger-500" : "text-success-500"
    bg = polaridade === "direta" ? "bg-danger-500/10" : "bg-success-500/10"
  }

  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", cor, bg)}>
      <Icone size={12} strokeWidth={1.5} aria-hidden />
      <span>{formatDeltaPercentual(delta, unidade)}</span>
    </span>
  )
}
