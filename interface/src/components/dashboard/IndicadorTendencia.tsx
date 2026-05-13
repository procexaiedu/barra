"use client"

import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  N_MINIMO_PARA_DELTA_PCT,
  calcularDeltaPercentual,
  formatDeltaAbsoluto,
  formatDeltaPercentual,
} from "./utils"

type Polaridade = "direta" | "invertida"

interface Props {
  atual: number
  anterior: number
  unidade: "%" | "pp"
  polaridade: Polaridade
  base?: "valor" | "pp"
  /** Quando informado, suprime delta % caso `baseAtual` ou `baseAnterior` < N_MINIMO. */
  baseAtual?: number | null
  baseAnterior?: number | null
}

export function IndicadorTendencia({
  atual,
  anterior,
  unidade,
  polaridade,
  baseAtual,
  baseAnterior,
}: Props) {
  if (atual === 0 && anterior === 0) {
    return (
      <span className="inline-flex items-center text-xs font-medium text-text-muted">—</span>
    )
  }

  if (anterior === 0 && atual === 0) {
    return (
      <span className="inline-flex items-center text-xs font-medium text-text-muted">—</span>
    )
  }

  const basePequena =
    (baseAtual !== undefined && baseAtual !== null && baseAtual < N_MINIMO_PARA_DELTA_PCT) ||
    (baseAnterior !== undefined && baseAnterior !== null && baseAnterior < N_MINIMO_PARA_DELTA_PCT)

  // Quando base é pequena, mostramos delta absoluto (contagem) — % infla muito com n<10.
  const usarAbsoluto = basePequena && unidade === "%"

  const delta = unidade === "pp" ? atual - anterior : calcularDeltaPercentual(atual, anterior)
  const absDelta = Math.abs(delta)
  const zeroEfetivo = usarAbsoluto ? atual === anterior : absDelta < 0.05

  let cor = "text-text-muted"
  let bg = ""
  let Icone = Minus
  const direcao = usarAbsoluto ? Math.sign(atual - anterior) : Math.sign(delta)

  if (zeroEfetivo) {
    Icone = Minus
    cor = "text-text-muted"
    bg = ""
  } else if (direcao > 0) {
    Icone = ArrowUp
    cor = polaridade === "direta" ? "text-success-500" : "text-danger-500"
    bg = polaridade === "direta" ? "bg-success-500/10" : "bg-danger-500/10"
  } else {
    Icone = ArrowDown
    cor = polaridade === "direta" ? "text-danger-500" : "text-success-500"
    bg = polaridade === "direta" ? "bg-danger-500/10" : "bg-success-500/10"
  }

  const titulo = basePequena
    ? `Base pequena (n atual=${baseAtual ?? "?"}, n anterior=${baseAnterior ?? "?"}) — exibindo delta absoluto`
    : undefined

  return (
    <span
      title={titulo}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cor,
        bg
      )}
    >
      <Icone size={12} strokeWidth={1.5} aria-hidden />
      <span>{usarAbsoluto ? formatDeltaAbsoluto(atual, anterior) : formatDeltaPercentual(delta, unidade)}</span>
    </span>
  )
}
