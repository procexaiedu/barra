"use client"

import { useMemo, useState } from "react"
import { Calendar as CalendarIcon } from "lucide-react"

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { RangeCalendar } from "@/components/ui/range-calendar"
import { cn } from "@/lib/utils"
import {
  fimMesBrtIso,
  fimSemanaBrtIso,
  formatarDiaMes,
  hojeBrtIso,
  inicioMesBrtIso,
  inicioSemanaBrtIso,
} from "@/lib/datas"
import type { PeriodoFiltro } from "@/tipos/atendimentos"

type Preset = "hoje" | "semana" | "mes" | "custom"

interface Props {
  value: PeriodoFiltro
  onChange: (proximo: PeriodoFiltro) => void
}

function presetAtual(value: PeriodoFiltro): Preset {
  const hoje = hojeBrtIso()
  if (value.de === hoje && value.ate === hoje) return "hoje"
  if (value.de === inicioSemanaBrtIso() && value.ate === fimSemanaBrtIso()) return "semana"
  if (value.de === inicioMesBrtIso() && value.ate === fimMesBrtIso()) return "mes"
  return "custom"
}

function rotulo(value: PeriodoFiltro, modoCustom: boolean): string {
  if (!modoCustom) {
    const preset = presetAtual(value)
    if (preset === "hoje") return "Hoje"
    if (preset === "semana") return "Esta semana"
    if (preset === "mes") return "Este mês"
  }
  if (value.de && value.ate) return `${formatarDiaMes(value.de)} – ${formatarDiaMes(value.ate)}`
  if (value.de) return `Desde ${formatarDiaMes(value.de)}`
  if (value.ate) return `Até ${formatarDiaMes(value.ate)}`
  return "Período"
}

export function FiltroPeriodo({ value, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [modoCustom, setModoCustom] = useState(false)
  const presetDetectado = useMemo(() => presetAtual(value), [value])
  const presetEfetivo: Preset = modoCustom ? "custom" : presetDetectado
  const label = useMemo(() => rotulo(value, modoCustom), [value, modoCustom])

  const aplicarPreset = (proximo: Preset) => {
    if (proximo === "custom") {
      setModoCustom(true)
      return
    }
    setModoCustom(false)
    if (proximo === "hoje") {
      const hoje = hojeBrtIso()
      onChange({ de: hoje, ate: hoje })
    } else if (proximo === "semana") {
      onChange({ de: inicioSemanaBrtIso(), ate: fimSemanaBrtIso() })
    } else if (proximo === "mes") {
      onChange({ de: inicioMesBrtIso(), ate: fimMesBrtIso() })
    }
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Período</span>
        <PopoverTrigger
          data-slot="filtro-periodo-trigger"
          className="inline-flex h-9 w-full items-center justify-between gap-1.5 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="truncate">{label}</span>
          <CalendarIcon size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
        </PopoverTrigger>
      </label>
      <PopoverContent
        data-slot="filtro-periodo-content"
        align="end"
        className="flex w-[320px] flex-col gap-3 sm:w-[360px]"
      >
        <div className="flex flex-wrap gap-1.5">
          <PresetBotao ativo={presetEfetivo === "hoje"} onClick={() => aplicarPreset("hoje")}>
            Hoje
          </PresetBotao>
          <PresetBotao ativo={presetEfetivo === "semana"} onClick={() => aplicarPreset("semana")}>
            Esta semana
          </PresetBotao>
          <PresetBotao ativo={presetEfetivo === "mes"} onClick={() => aplicarPreset("mes")}>
            Este mês
          </PresetBotao>
          <PresetBotao ativo={presetEfetivo === "custom"} onClick={() => aplicarPreset("custom")}>
            Personalizado
          </PresetBotao>
        </div>
        {presetEfetivo === "custom" ? (
          <div className="flex justify-center">
            <RangeCalendar
              value={value}
              onChange={(range) => onChange(range)}
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
          ? "border-primary bg-primary/10 text-text-primary"
          : "border-border bg-muted text-text-secondary hover:border-border-strong hover:text-text-primary"
      )}
    >
      {children}
    </button>
  )
}
