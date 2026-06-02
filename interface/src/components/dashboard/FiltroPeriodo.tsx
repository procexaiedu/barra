"use client"

import type { FiltroPeriodo as FiltroPeriodoTipo } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { formatRangeAbsoluto } from "./utils"

type PresetValue = "hoje" | "7d" | "30d" | "tudo"

interface Props {
  periodo: FiltroPeriodoTipo
  de: string | null
  ate: string | null
  onPreset: (periodo: PresetValue) => void
  onAbrirCustom: () => void
}

const PRESETS: { value: PresetValue; label: string }[] = [
  { value: "hoje", label: "Hoje" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "tudo", label: "Tudo" },
]

export function FiltroPeriodo({ periodo, de, ate, onPreset, onAbrirCustom }: Props) {
  const customAtivo = periodo === "custom"
  const segmentoBase =
    "rounded-md px-2.5 py-1.5 text-sm font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
  return (
    <div
      className="flex h-9 items-center rounded-lg border border-border bg-muted p-0.5"
      role="group"
      aria-label="Período"
    >
      {PRESETS.map((p) => {
        const ativo = periodo === p.value
        return (
          <button
            key={p.value}
            type="button"
            onClick={() => onPreset(p.value)}
            aria-pressed={ativo}
            className={cn(
              segmentoBase,
              ativo
                ? "bg-accent text-text-brand"
                : "text-text-muted hover:text-text-primary"
            )}
          >
            {p.label}
          </button>
        )
      })}
      <button
        type="button"
        onClick={onAbrirCustom}
        aria-pressed={customAtivo}
        className={cn(
          segmentoBase,
          customAtivo
            ? "bg-accent text-text-brand"
            : "text-text-muted hover:text-text-primary"
        )}
      >
        {customAtivo && de && ate ? (
          <span className="font-mono text-[12px] tabular-nums text-text-brand">
            {formatRangeAbsoluto(de, ate)}
          </span>
        ) : (
          "Personalizado…"
        )}
      </button>
    </div>
  )
}
