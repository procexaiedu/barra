"use client"

import * as React from "react"
import {
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Minus,
} from "lucide-react"
import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import { Sparkline } from "./charts/Sparkline"

export type KpiTom = "default" | "brand" | "warning" | "success" | "danger" | "muted"

// Acima desse percentual o delta vira ruidoso (baseline ~zero) — viz literatura
// chama isso de "low base effect". Mostramos só a diferença absoluta + chip
// neutro "vs ~zero" pra não pintar de verde uma variação que não tem escala.
const PCT_EXPLOSAO = 500

interface KpiCardProps {
  rotulo: string
  valor: number
  anterior?: number | null
  formato?: "brl" | "int"
  hint?: React.ReactNode
  tom?: KpiTom
  destaque?: boolean
  sentido?: "maior_melhor" | "maior_pior" | "neutro"
  icone?: React.ReactNode
  trailing?: React.ReactNode
  progresso?: number
  okQuando?: boolean
  okTexto?: string
  sparkline?: number[]
  corSparkline?: string
}

const TONS: Record<KpiTom, { valor: string; borda: string; chip: string }> = {
  default: {
    valor: "text-text-primary",
    borda: "border-border",
    chip: "bg-muted/50 text-text-muted",
  },
  brand: {
    valor: "text-gold-700",
    borda: "border-border",
    chip: "bg-gold-700/10 text-gold-700",
  },
  warning: {
    valor: "text-warn-500",
    borda: "border-warn-500/40",
    chip: "bg-warn-500/15 text-warn-500",
  },
  success: {
    valor: "text-success-500",
    borda: "border-border",
    chip: "bg-success-500/15 text-success-500",
  },
  danger: {
    valor: "text-danger-500",
    borda: "border-danger-500/40",
    chip: "bg-danger-500/12 text-danger-500",
  },
  muted: {
    valor: "text-text-muted",
    borda: "border-border",
    chip: "bg-muted/50 text-text-muted",
  },
}

export function KpiCard({
  rotulo,
  valor,
  anterior = null,
  formato = "brl",
  hint,
  tom = "default",
  destaque = false,
  sentido = "maior_melhor",
  icone,
  trailing,
  progresso,
  okQuando,
  okTexto,
  sparkline,
  corSparkline,
}: KpiCardProps) {
  const tons = TONS[tom]
  const formatado =
    formato === "brl"
      ? formatBRL(valor)
      : new Intl.NumberFormat("pt-BR").format(valor)

  const delta = computarDelta(valor, anterior)
  const destaqueBorda = destaque ? "border-gold-500/50" : tons.borda
  const temSparkline = Array.isArray(sparkline) && sparkline.length >= 2
  const corSpark =
    corSparkline ??
    (tom === "brand"
      ? "var(--gold-500)"
      : tom === "danger"
        ? "var(--danger-500)"
        : tom === "warning"
          ? "var(--warn-500)"
          : tom === "success"
            ? "var(--success-500)"
            : "var(--text-secondary)")

  return (
    <div
      data-tom={tom}
      data-destaque={destaque || undefined}
      className={cn(
        "relative flex flex-col gap-2 rounded-md border bg-card p-3",
        destaqueBorda,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
          {rotulo}
        </span>
        {icone && <span aria-hidden className="shrink-0 text-text-muted">{icone}</span>}
      </div>

      {okQuando ? (
        <div className="flex items-center gap-2 text-success-500">
          <CheckCircle2 className="size-5" aria-hidden />
          <span className="text-[14px] font-medium">{okTexto ?? "tudo em dia"}</span>
        </div>
      ) : (
        <div className="flex items-baseline gap-2">
          <span
            className={cn(
              "font-semibold tabular-nums leading-none",
              destaque ? "text-[28px]" : "text-[22px]",
              tons.valor,
            )}
          >
            {formatado}
          </span>
          {trailing && <span className="text-[11px] text-text-muted">{trailing}</span>}
        </div>
      )}

      {typeof progresso === "number" && !okQuando && (
        <div
          className="h-[3px] w-full overflow-hidden rounded-sm bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(progresso)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-primary transition-[width] duration-500 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, progresso))}%` }}
          />
        </div>
      )}

      {temSparkline && !okQuando && (
        <Sparkline
          valores={sparkline!}
          cor={corSpark}
          alturaPx={destaque ? 32 : 24}
          rotuloAcessivel={`Tendência de ${rotulo.toLowerCase()} no período`}
        />
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {delta && !okQuando && (
          <DeltaChip delta={delta} sentido={sentido} classe={tons.chip} />
        )}
        {hint && (
          <span className="text-[11px] leading-tight text-text-muted">{hint}</span>
        )}
      </div>
    </div>
  )
}

interface Delta {
  pct: number | null
  diffAbs: number
  formato: "brl" | "int"
  direcao: "subiu" | "desceu" | "igual" | "novo"
}

function computarDelta(valor: number, anterior: number | null): Delta | null {
  if (anterior === null || anterior === undefined) return null
  if (anterior === 0 && valor === 0) return null
  const diffAbs = valor - anterior
  const formato: "brl" | "int" =
    Number.isInteger(valor) && Number.isInteger(anterior) ? "int" : "brl"
  if (Math.abs(anterior) < 0.005) {
    return { pct: null, diffAbs, formato, direcao: "novo" }
  }
  const pct = (diffAbs / Math.abs(anterior)) * 100
  // Baseline ~zero relativo: anterior é tão pequeno que a % vira ruído (ver
  // PCT_EXPLOSAO). Trata como "novo período" — mantém o abs (carrega a escala
  // real) e descarta o percent enganoso.
  if (Math.abs(pct) > PCT_EXPLOSAO) {
    return { pct: null, diffAbs, formato, direcao: "novo" }
  }
  return {
    pct,
    diffAbs,
    formato,
    direcao: pct > 0.05 ? "subiu" : pct < -0.05 ? "desceu" : "igual",
  }
}

function formatarDiffAbs(diff: number, formato: "brl" | "int") {
  const abs = Math.abs(diff)
  const sinal = diff > 0 ? "+" : diff < 0 ? "−" : ""
  return formato === "brl"
    ? `${sinal}${formatBRL(abs)}`
    : `${sinal}${new Intl.NumberFormat("pt-BR").format(abs)}`
}

function DeltaChip({
  delta,
  sentido,
  classe,
}: {
  delta: Delta
  sentido: "maior_melhor" | "maior_pior" | "neutro"
  classe: string
}) {
  if (delta.direcao === "novo") {
    return (
      <span className="inline-flex items-center gap-1 rounded-sm bg-muted/60 px-1.5 py-0.5 text-[10.5px] font-medium uppercase tracking-wide text-text-muted">
        novo período
        <span className="tabular-nums normal-case tracking-normal opacity-80">
          {formatarDiffAbs(delta.diffAbs, delta.formato)}
        </span>
      </span>
    )
  }

  const positivo =
    sentido === "neutro"
      ? null
      : (delta.direcao === "subiu" && sentido === "maior_melhor") ||
        (delta.direcao === "desceu" && sentido === "maior_pior")

  const cor =
    delta.direcao === "igual"
      ? "bg-muted/50 text-text-muted"
      : positivo === null
        ? classe
        : positivo
          ? "bg-success-500/15 text-success-500"
          : "bg-danger-500/12 text-danger-500"

  const Icone =
    delta.direcao === "igual"
      ? Minus
      : delta.direcao === "subiu"
        ? ArrowUpRight
        : ArrowDownRight

  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-sm px-1.5 text-[10.5px] font-medium tabular-nums",
        cor,
      )}
    >
      <Icone className="size-3" aria-hidden />
      <span>{formatarDiffAbs(delta.diffAbs, delta.formato)}</span>
      {delta.pct !== null && (
        <span className="opacity-70">({delta.pct >= 0 ? "+" : ""}{delta.pct.toFixed(1)}%)</span>
      )}
    </span>
  )
}
