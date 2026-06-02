"use client"

import { useState } from "react"
import { Calendar } from "lucide-react"
import { cn } from "@/lib/utils"
import { DialogRangeCustom } from "@/components/dashboard/DialogRangeCustom"
import { FiltroModeloMulti } from "@/components/dashboard/FiltroModeloMulti"
import { formatRangeAbsoluto } from "@/components/dashboard/utils"
import type { FiltroPeriodo } from "@/tipos/dashboard"
import type { useFinanceiro } from "@/hooks/useFinanceiro"

const PRESETS: { id: Exclude<FiltroPeriodo, "custom">; label: string }[] = [
  { id: "hoje", label: "Hoje" },
  { id: "7d", label: "7 dias" },
  { id: "30d", label: "30 dias" },
  { id: "mes", label: "Mês" },
  { id: "tudo", label: "Tudo" },
]

export function ToolbarFinanceiro({
  fin,
}: {
  fin: ReturnType<typeof useFinanceiro>
}) {
  const [rangeOpen, setRangeOpen] = useState(false)
  const { filtros } = fin
  const view = filtros.view

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border bg-muted/30 p-2">
        <div className="flex rounded-lg border border-border bg-muted p-0.5">
          {PRESETS.map((p) => {
            const ativo = filtros.periodo === p.id
            return (
              <button
                key={p.id}
                type="button"
                aria-pressed={ativo}
                onClick={() => fin.setPeriodoPreset(p.id)}
                className="rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-150 aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm text-text-muted hover:text-text-primary"
              >
                {p.label}
              </button>
            )
          })}
          <button
            type="button"
            aria-pressed={filtros.periodo === "custom"}
            onClick={() => setRangeOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-150 aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm text-text-muted hover:text-text-primary"
          >
            <Calendar size={14} strokeWidth={1.5} />
            {filtros.periodo === "custom" && filtros.de && filtros.ate
              ? formatRangeAbsoluto(filtros.de, filtros.ate)
              : "Personalizar"}
          </button>
        </div>

        {view === "receitas" && (
          <FiltroForma
            valor={filtros.forma_pagamento}
            onChange={fin.setFormaPagamento}
          />
        )}

        <div className="flex flex-wrap items-center gap-2 border-l border-border pl-3">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            Modelo
          </span>
          <FiltroModeloMulti
            modeloIds={filtros.modelo_ids}
            onChange={fin.setModeloIds}
          />
        </div>
      </div>
      <DialogRangeCustom
        open={rangeOpen}
        onOpenChange={setRangeOpen}
        deAtual={filtros.periodo === "custom" ? filtros.de : null}
        ateAtual={filtros.periodo === "custom" ? filtros.ate : null}
        onAplicar={(de, ate) => {
          fin.setPeriodoCustom(de, ate)
          setRangeOpen(false)
        }}
      />
    </>
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
