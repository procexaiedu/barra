import { ChevronDown, ChevronLeft, ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { cn } from "@/lib/utils"
import type { VisaoAgenda } from "@/tipos/agenda"

const visoes: Array<{ value: VisaoAgenda; label: string }> = [
  { value: "dia", label: "Dia" },
  { value: "semana", label: "Semana" },
  { value: "mes", label: "Mês" },
]

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
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card p-2">
      <div className="flex items-center gap-3">
        {/* Segmented (§7.9): poço recuado + aba ativa elevada (bg-card) com marca dourada */}
        <div className="flex rounded-lg border border-border bg-muted p-0.5" aria-label="Visão da agenda">
          {visoes.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={visao === item.value}
              onClick={() => onVisaoChange(item.value)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                visao === item.value
                  ? "bg-card text-text-brand shadow-sm"
                  : "text-text-muted hover:text-text-primary"
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

      <div className="flex items-center gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">Modelo</span>
          <FiltroModelo
            multi={false}
            value={modeloId ? [modeloId] : []}
            onChange={(ids) => onModeloChange(ids[0] ?? null)}
          />
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">Tipo</span>
          <div className="relative">
            <select
              value={tipoAtendimento}
              onChange={(e) => onTipoAtendimentoChange(e.target.value as "" | "interno" | "externo")}
              className="h-9 w-full appearance-none rounded-lg border border-input bg-input pl-3 pr-8 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <option value="">Todos</option>
              <option value="interno">Interno</option>
              <option value="externo">Externo</option>
            </select>
            <ChevronDown
              size={14}
              strokeWidth={1.5}
              aria-hidden
              className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted"
            />
          </div>
        </label>

        <div className="ml-1 flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={onAnterior} aria-label="Período anterior">
            <ChevronLeft />
          </Button>
          <span className="min-w-44 text-center text-sm font-semibold capitalize tabular-nums text-text-primary">
            {periodoLabel}
          </span>
          <Button variant="ghost" size="icon" onClick={onProximo} aria-label="Próximo período">
            <ChevronRight />
          </Button>
          <Button variant="outline" size="sm" onClick={onHoje} className="ml-1">
            Hoje
          </Button>
        </div>
      </div>
    </div>
  )
}
