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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-muted/30 p-2">
      <FiltroPeriodo
        value={{ periodo: filtros.periodo, de: filtros.de, ate: filtros.ate }}
        onChange={onPeriodoChange}
        label="Período"
      />

      {view === "receitas" && (
        <FiltroForma valor={filtros.forma_pagamento} onChange={fin.setFormaPagamento} />
      )}

      <div className="flex flex-wrap items-center gap-2 border-l border-border pl-3">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
          Modelo
        </span>
        <FiltroModelo value={filtros.modelo_ids} onChange={fin.setModeloIds} />
      </div>
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
    <div className="flex flex-wrap items-center gap-2 border-l border-border pl-3">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        Forma
      </span>
      <div className="flex rounded-lg border border-border bg-muted p-0.5">
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
