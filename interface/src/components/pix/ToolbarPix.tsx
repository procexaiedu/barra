"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { SelectFiltro } from "@/components/filtros/SelectFiltro"
import type {
  FiltroPeriodoPix,
  FiltroStatusPix,
  MotivoRevisao,
} from "@/tipos/pix"
import {
  motivoRevisaoFiltroOptions,
  periodoFiltroOptions,
  statusFiltroOptions,
} from "./utils"

export function ToolbarPix({
  busca,
  status,
  modeloIds,
  motivo,
  periodo,
  loading,
  onBuscaChange,
  onStatusChange,
  onModeloChange,
  onMotivoChange,
  onPeriodoChange,
}: {
  busca: string
  status: FiltroStatusPix
  modeloIds: string[]
  motivo: MotivoRevisao | "todos"
  periodo: FiltroPeriodoPix
  loading: boolean
  onBuscaChange: (value: string) => void
  onStatusChange: (value: FiltroStatusPix) => void
  onModeloChange: (value: string[]) => void
  onMotivoChange: (value: MotivoRevisao | "todos") => void
  onPeriodoChange: (value: FiltroPeriodoPix) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(260px,1fr)_180px_160px_180px_140px] gap-3">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="flex flex-col gap-1">
            <Skeleton className="h-3.5 w-16 rounded" />
            <Skeleton className="h-9 rounded-lg" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(260px,1fr)_180px_160px_180px_140px] gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Buscar</span>
        <div className="relative">
          <Search
            size={16}
            strokeWidth={1.5}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <Input
            value={busca}
            onChange={(event) => onBuscaChange(event.target.value)}
            placeholder="Valor, cliente, telefone ou #N"
            className="pl-9"
          />
        </div>
      </label>
      <SelectFiltro
        label="Status"
        value={status}
        onChange={(value) => onStatusChange(value as FiltroStatusPix)}
      >
        {statusFiltroOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </SelectFiltro>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Modelo</span>
        <FiltroModelo value={modeloIds} onChange={onModeloChange} className="w-full" />
      </label>
      <SelectFiltro
        label="Motivo de revisão"
        value={motivo}
        onChange={(value) => onMotivoChange(value as MotivoRevisao | "todos")}
      >
        {motivoRevisaoFiltroOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </SelectFiltro>
      <SelectFiltro
        label="Período"
        value={periodo}
        onChange={(value) => onPeriodoChange(value as FiltroPeriodoPix)}
      >
        {periodoFiltroOptions.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </SelectFiltro>
    </div>
  )
}
