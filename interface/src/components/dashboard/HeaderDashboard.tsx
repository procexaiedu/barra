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

export function HeaderDashboard({
  periodo,
  modeloIds,
  rangeComparacao,
  onPeriodoChange,
  onModeloChange,
}: Props) {
  return (
    <header className="flex flex-col gap-2 border-b border-border pb-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
            Dashboard
          </h1>
          <p className="mt-1 text-[13px] text-text-muted">
            Resultado, operação e financeiro da Elite Baby no período selecionado.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <FiltroPeriodo value={periodo} onChange={onPeriodoChange} />
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-text-muted">Modelo</span>
            <FiltroModelo value={modeloIds} onChange={onModeloChange} />
          </div>
        </div>
      </div>
      {rangeComparacao ? (
        <p className="text-right font-mono text-[11px] text-text-muted">
          Comparando com {rangeComparacao}
        </p>
      ) : null}
    </header>
  )
}
