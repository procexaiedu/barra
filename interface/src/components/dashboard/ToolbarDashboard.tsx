"use client"

import { FiltroModelo } from "./FiltroModelo"
import { FiltroPeriodo } from "./FiltroPeriodo"
import type { FiltroPeriodo as FiltroPeriodoTipo } from "@/tipos/dashboard"

interface Props {
  periodo: FiltroPeriodoTipo
  de: string | null
  ate: string | null
  modeloId: string | null
  onPreset: (periodo: "hoje" | "7d" | "30d" | "tudo") => void
  onAbrirCustom: () => void
  onModeloChange: (modeloId: string | null) => void
}

export function ToolbarDashboard({
  periodo,
  de,
  ate,
  modeloId,
  onPreset,
  onAbrirCustom,
  onModeloChange,
}: Props) {
  return (
    <section
      aria-label="Filtros do dashboard"
      className="flex flex-wrap items-center justify-between gap-3"
    >
      <FiltroPeriodo
        periodo={periodo}
        de={de}
        ate={ate}
        onPreset={onPreset}
        onAbrirCustom={onAbrirCustom}
      />
      <FiltroModelo modeloId={modeloId} onChange={onModeloChange} />
    </section>
  )
}
