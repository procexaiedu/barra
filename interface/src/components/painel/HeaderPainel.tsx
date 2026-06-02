"use client"

import { FiltroModelo } from "@/components/filtros/FiltroModelo"

export function HeaderPainel({
  modeloIds,
  onModeloChange,
}: {
  modeloIds: string[]
  onModeloChange: (ids: string[]) => void
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
          Painel
        </h1>
        <p className="mt-1 text-[13px] text-text-muted">
          Tudo que precisa da sua atenção, num só lugar.
        </p>
      </div>
      <div className="flex flex-col items-start gap-1">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
          Modelo
        </span>
        <FiltroModelo value={modeloIds} onChange={onModeloChange} />
      </div>
    </header>
  )
}
