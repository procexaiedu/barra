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
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Período">
      {PRESETS.map((p) => {
        const ativo = periodo === p.value
        return (
          <button
            key={p.value}
            type="button"
            onClick={() => onPreset(p.value)}
            aria-pressed={ativo}
            className={cn(
              "h-9 rounded-md px-3 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              ativo
                ? "bg-ink-300 text-gold-500"
                : "bg-ink-200 text-text-secondary hover:bg-ink-300 hover:text-text-primary"
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
          "h-9 rounded-md px-3 text-sm font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          customAtivo
            ? "bg-ink-300 text-gold-500"
            : "bg-ink-200 text-text-secondary hover:bg-ink-300 hover:text-text-primary"
        )}
      >
        {customAtivo && de && ate ? (
          <span className="font-mono text-[12px] text-gold-500">
            {formatRangeAbsoluto(de, ate)}
          </span>
        ) : (
          "Personalizado…"
        )}
      </button>
    </div>
  )
}
