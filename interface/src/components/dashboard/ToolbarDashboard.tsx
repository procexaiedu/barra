"use client"

import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import type { PeriodoSelecionado } from "@/tipos/filtros"

interface Props {
  periodo: PeriodoSelecionado
  modeloIds: string[]
  rangeComparacao: string | null
  onPeriodoChange: (value: PeriodoSelecionado) => void
  onModeloChange: (modeloIds: string[]) => void
}

export function ToolbarDashboard({
  periodo,
  modeloIds,
  rangeComparacao,
  onPeriodoChange,
  onModeloChange,
}: Props) {
  return (
    <section aria-label="Filtros do dashboard" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <FiltroPeriodo value={periodo} onChange={onPeriodoChange} />
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Modelo</span>
          <FiltroModelo value={modeloIds} onChange={onModeloChange} />
        </div>
      </div>
      {rangeComparacao ? (
        <p className="font-mono text-[11px] text-text-muted">Comparando com {rangeComparacao}</p>
      ) : null}
    </section>
  )
}
