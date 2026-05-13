"use client"

import { FiltroModelo } from "./FiltroModelo"
import { FiltroPeriodo } from "./FiltroPeriodo"
import type { FiltroPeriodo as FiltroPeriodoTipo } from "@/tipos/dashboard"

interface Props {
  periodo: FiltroPeriodoTipo
  de: string | null
  ate: string | null
  modeloId: string | null
  rangeComparacao: string | null
  onPreset: (periodo: "hoje" | "7d" | "30d" | "tudo") => void
  onAbrirCustom: () => void
  onModeloChange: (modeloId: string | null) => void
}

export function ToolbarDashboard({
  periodo,
  de,
  ate,
  modeloId,
  rangeComparacao,
  onPreset,
  onAbrirCustom,
  onModeloChange,
}: Props) {
  return (
    <section aria-label="Filtros do dashboard" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Período</span>
          <FiltroPeriodo
            periodo={periodo}
            de={de}
            ate={ate}
            onPreset={onPreset}
            onAbrirCustom={onAbrirCustom}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Modelo</span>
          <FiltroModelo modeloId={modeloId} onChange={onModeloChange} />
        </div>
      </div>
      {rangeComparacao ? (
        <p className="font-mono text-[11px] text-text-muted">
          Comparando com {rangeComparacao}
        </p>
      ) : null}
    </section>
  )
}
