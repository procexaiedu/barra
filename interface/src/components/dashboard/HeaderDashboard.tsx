"use client"

import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import { PageHeader } from "@/components/layout/PageHeader"
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
    <div className="flex flex-col gap-2 border-b border-border pb-5">
      <PageHeader
        title="Dashboard"
        description="Resultado, operação e financeiro da Elite Baby no período selecionado."
      >
        <FiltroPeriodo value={periodo} onChange={onPeriodoChange} />
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Modelo</span>
          <FiltroModelo value={modeloIds} onChange={onModeloChange} />
        </div>
      </PageHeader>
      {rangeComparacao ? (
        <p className="text-right font-mono text-[11px] text-text-muted">
          Comparando com {rangeComparacao}
        </p>
      ) : null}
    </div>
  )
}
