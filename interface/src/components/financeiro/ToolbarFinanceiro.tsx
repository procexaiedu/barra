"use client"

import { cn } from "@/lib/utils"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import type { PeriodoSelecionado } from "@/tipos/filtros"
import type { useFinanceiro } from "@/hooks/useFinanceiro"

export function ToolbarFinanceiro({
  fin,
}: {
  fin: ReturnType<typeof useFinanceiro>
}) {
  const { filtros } = fin
  const view = filtros.view

  const onPeriodoChange = (v: PeriodoSelecionado) => {
    if (v.periodo === "custom") {
      if (v.de && v.ate) fin.setPeriodoCustom(v.de, v.ate)
    } else {
      fin.setPeriodoPreset(v.periodo)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <FiltroPeriodo
        value={{ periodo: filtros.periodo, de: filtros.de, ate: filtros.ate }}
        onChange={onPeriodoChange}
      />
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Modelo</span>
        <FiltroModelo value={filtros.modelo_ids} onChange={fin.setModeloIds} />
      </div>
      {view === "receitas" && (
        <FiltroForma valor={filtros.forma_pagamento} onChange={fin.setFormaPagamento} />
      )}
    </div>
  )
}

function FiltroForma({
  valor,
  onChange,
}: {
  valor: string | null
  onChange: (v: "pix" | "dinheiro" | "cartao" | "outro" | null) => void
}) {
  const opcoes = ["pix", "dinheiro", "cartao", "outro"] as const
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">Forma</span>
      <div className="flex h-9 items-center rounded-lg border border-border bg-muted p-0.5">
        <SegForma ativo={!valor} onClick={() => onChange(null)}>
          todas
        </SegForma>
        {opcoes.map((o) => (
          <SegForma key={o} ativo={valor === o} onClick={() => onChange(o)}>
            {o}
          </SegForma>
        ))}
      </div>
    </div>
  )
}

function SegForma({
  ativo,
  onClick,
  children,
}: {
  ativo: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={ativo}
      onClick={onClick}
      className={cn(
        "rounded-md px-2 py-1 text-xs font-medium capitalize transition-all duration-150",
        "aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm",
        "text-text-muted hover:text-text-primary",
      )}
    >
      {children}
    </button>
  )
}
