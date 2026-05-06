import { ChevronLeft, ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FiltroModelo } from "@/components/dashboard/FiltroModelo"
import { cn } from "@/lib/utils"
import type { VisaoAgenda } from "@/tipos/agenda"

const visoes: Array<{ value: VisaoAgenda; label: string }> = [
  { value: "dia", label: "Dia" },
  { value: "semana", label: "Semana" },
  { value: "mes", label: "Mês" },
]

const selectClassName =
  "h-9 rounded-md border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"

export function ToolbarAgenda({
  visao,
  periodoLabel,
  modeloId,
  tipoAtendimento,
  onVisaoChange,
  onAnterior,
  onProximo,
  onHoje,
  onModeloChange,
  onTipoAtendimentoChange,
  onCriar,
}: {
  visao: VisaoAgenda
  periodoLabel: string
  modeloId: string | null
  tipoAtendimento: "" | "interno" | "externo"
  onVisaoChange: (visao: VisaoAgenda) => void
  onAnterior: () => void
  onProximo: () => void
  onHoje: () => void
  onModeloChange: (modeloId: string | null) => void
  onTipoAtendimentoChange: (tipo: "" | "interno" | "externo") => void
  onCriar?: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-3">
        <div className="flex rounded-lg bg-muted p-1" aria-label="Visão da agenda">
          {visoes.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onVisaoChange(item.value)}
              className={cn(
                "h-8 rounded-md px-3 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
                visao === item.value
                  ? "bg-card text-text-brand"
                  : "text-text-secondary hover:text-text-primary"
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
        {onCriar && (
          <Button variant="primary" size="sm" onClick={onCriar}>
            <Plus />
            Novo
          </Button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2">
          <span className="text-sm text-text-secondary">Modelo</span>
          <FiltroModelo modeloId={modeloId} onChange={onModeloChange} />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-sm text-text-secondary">Tipo</span>
          <select
            value={tipoAtendimento}
            onChange={(e) => onTipoAtendimentoChange(e.target.value as "" | "interno" | "externo")}
            className={selectClassName}
          >
            <option value="">Todos</option>
            <option value="interno">Interno</option>
            <option value="externo">Externo</option>
          </select>
        </label>
        <div className="mx-2 h-6 w-[1px] bg-border" />
        <Button variant="ghost" size="icon" onClick={onAnterior} aria-label="Período anterior">
          <ChevronLeft />
        </Button>
        <span className="min-w-48 text-center text-sm font-semibold text-text-primary capitalize">
          {periodoLabel}
        </span>
        <Button variant="ghost" size="icon" onClick={onProximo} aria-label="Próximo período">
          <ChevronRight />
        </Button>
        <Button variant="ghost" onClick={onHoje}>
          Hoje
        </Button>
      </div>
    </div>
  )
}
