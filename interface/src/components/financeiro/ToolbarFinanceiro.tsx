"use client"

import { useState } from "react"
import { Calendar } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DialogRangeCustom } from "@/components/dashboard/DialogRangeCustom"
import { formatRangeAbsoluto } from "@/components/dashboard/utils"
import { CATEGORIAS_DESPESA, ROTULO_CATEGORIA, type CategoriaDespesa } from "@/tipos/financeiro"
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
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3">
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <Button
              key={p.id}
              variant={filtros.periodo === p.id ? "primary" : "ghost"}
              size="sm"
              onClick={() => fin.setPeriodoPreset(p.id)}
            >
              {p.label}
            </Button>
          ))}
          <Button
            variant={filtros.periodo === "custom" ? "primary" : "ghost"}
            size="sm"
            onClick={() => setRangeOpen(true)}
          >
            <Calendar className="size-3.5" />
            {filtros.periodo === "custom" && filtros.de && filtros.ate
              ? formatRangeAbsoluto(filtros.de, filtros.ate)
              : "Personalizar"}
          </Button>
        </div>

        {view === "despesas" && (
          <FiltroCategorias
            selecionadas={filtros.categoria}
            onChange={fin.setCategoria}
          />
        )}

        {view === "receitas" && (
          <FiltroForma
            valor={filtros.forma_pagamento}
            onChange={fin.setFormaPagamento}
          />
        )}
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

function FiltroCategorias({
  selecionadas,
  onChange,
}: {
  selecionadas: CategoriaDespesa[]
  onChange: (cats: CategoriaDespesa[]) => void
}) {
  const toggle = (c: CategoriaDespesa) => {
    if (selecionadas.includes(c)) onChange(selecionadas.filter((x) => x !== c))
    else onChange([...selecionadas, c])
  }
  return (
    <div className="flex flex-wrap items-center gap-1 border-l border-border pl-2">
      <span className="text-xs text-text-muted">Categoria:</span>
      {CATEGORIAS_DESPESA.map((c) => (
        <Button
          key={c}
          variant={selecionadas.includes(c) ? "primary" : "ghost"}
          size="xs"
          onClick={() => toggle(c)}
        >
          {ROTULO_CATEGORIA[c]}
        </Button>
      ))}
      {selecionadas.length > 0 && (
        <Button variant="ghost" size="xs" onClick={() => onChange([])}>
          limpar
        </Button>
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
    <div className="flex flex-wrap items-center gap-1 border-l border-border pl-2">
      <span className="text-xs text-text-muted">Forma:</span>
      <Button
        variant={!valor ? "primary" : "ghost"}
        size="xs"
        onClick={() => onChange(null)}
      >
        todas
      </Button>
      {opcoes.map((o) => (
        <Button
          key={o}
          variant={valor === o ? "primary" : "ghost"}
          size="xs"
          onClick={() => onChange(o)}
        >
          {o}
        </Button>
      ))}
    </div>
  )
}
