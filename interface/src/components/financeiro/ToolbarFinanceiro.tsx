"use client"

import { cn } from "@/lib/utils"
import type { useFinanceiro } from "@/hooks/useFinanceiro"

export function ToolbarFinanceiro({
  fin,
}: {
  fin: ReturnType<typeof useFinanceiro>
}) {
  const { filtros } = fin

  // Período e Modelo vivem no header; aqui ficam só os filtros específicos da view.
  if (filtros.view !== "receitas") return null

  return (
    <div className="flex flex-wrap items-end gap-2">
      <FiltroForma valor={filtros.forma_pagamento} onChange={fin.setFormaPagamento} />
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
        "aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm aria-[pressed=true]:ring-1 aria-[pressed=true]:ring-border-subtle",
        "text-text-muted hover:text-text-primary",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      {children}
    </button>
  )
}
