"use client"

import { useMemo, useState } from "react"
import { Calendar as CalendarIcon } from "lucide-react"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { RangeCalendar } from "@/components/ui/range-calendar"
import { cn } from "@/lib/utils"
import { resolverPresetPeriodo, rotuloPeriodo } from "@/lib/datas"
import {
  PERIODO_LABEL,
  PRESETS_PERIODO_PADRAO,
  type PeriodoSelecionado,
  type PresetPeriodo,
} from "@/tipos/filtros"

interface Props {
  value: PeriodoSelecionado
  onChange: (proximo: PeriodoSelecionado) => void
  /** Presets exibidos (default = conjunto completo). "custom" é sempre oferecido
   *  como "Personalizado", fora desta lista. */
  presets?: PresetPeriodo[]
  /** Label de acessibilidade / rótulo acima do gatilho. */
  label?: string
  className?: string
}

/** Seletor de período padrão do painel (Popover compacto + pills). Substitui as
 *  três UIs antigas (barra do dashboard, barra do financeiro, select dos clientes).
 *  O valor carrega `periodo` (nomeado) + `de/ate` resolvidos — cada surface manda
 *  ao backend o que seu endpoint espera (analytics: `periodo`; listas: `de/ate`). */
export function FiltroPeriodo({
  value,
  onChange,
  presets = PRESETS_PERIODO_PADRAO,
  label = "Período",
  className,
}: Props) {
  const [open, setOpen] = useState(false)
  const [modoCustom, setModoCustom] = useState(value.periodo === "custom")
  // Rascunho local do range em construção: o calendário emite `de` e depois `ate`
  // em cliques separados; só propagamos ao parent quando ambos existem.
  const [rascunho, setRascunho] = useState<{ de: string | null; ate: string | null }>({
    de: value.de,
    ate: value.ate,
  })
  const presetEfetivo: PresetPeriodo = modoCustom ? "custom" : value.periodo
  const rotulo = useMemo(() => rotuloPeriodo(value), [value])

  const aplicarPreset = (proximo: PresetPeriodo) => {
    if (proximo === "custom") {
      setModoCustom(true)
      setRascunho({ de: value.de, ate: value.ate })
      return
    }
    setModoCustom(false)
    const { de, ate } = resolverPresetPeriodo(proximo)
    onChange({ periodo: proximo, de, ate })
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(prox) => {
        setOpen(prox)
        if (!prox) setModoCustom(value.periodo === "custom")
      }}
    >
      <label className={cn("flex flex-col gap-1", className)}>
        <span className="text-xs font-medium text-text-muted">{label}</span>
        <PopoverTrigger
          data-slot="filtro-periodo-trigger"
          className="inline-flex h-9 w-full items-center justify-between gap-1.5 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="truncate">{rotulo}</span>
          <CalendarIcon size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
        </PopoverTrigger>
      </label>
      <PopoverContent
        data-slot="filtro-periodo-content"
        align="end"
        className="flex w-[320px] flex-col gap-3 sm:w-[360px]"
      >
        <div className="flex flex-wrap gap-1.5">
          {presets.map((p) => (
            <PresetBotao
              key={p}
              ativo={presetEfetivo === p}
              onClick={() => aplicarPreset(p)}
            >
              {PERIODO_LABEL[p]}
            </PresetBotao>
          ))}
          <PresetBotao ativo={presetEfetivo === "custom"} onClick={() => aplicarPreset("custom")}>
            {PERIODO_LABEL.custom}
          </PresetBotao>
        </div>
        {presetEfetivo === "custom" ? (
          <div className="flex justify-center">
            <RangeCalendar
              value={rascunho}
              onChange={(range) => {
                setRascunho(range)
                if (range.de && range.ate) {
                  onChange({ periodo: "custom", de: range.de, ate: range.ate })
                  setOpen(false)
                }
              }}
            />
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}

function PresetBotao({
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
      onClick={onClick}
      data-slot="filtro-periodo-preset"
      data-ativo={ativo ? "true" : undefined}
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        ativo
          ? "border-gold-500/60 bg-gold-500/10 text-text-primary"
          : "border-border bg-muted text-text-secondary hover:border-border-strong hover:text-text-primary"
      )}
    >
      {children}
    </button>
  )
}
