import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
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
  onVisaoChange,
  onAnterior,
  onProximo,
  onHoje,
}: {
  visao: VisaoAgenda
  periodoLabel: string
  onVisaoChange: (visao: VisaoAgenda) => void
  onAnterior: () => void
  onProximo: () => void
  onHoje: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-card p-3">
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

      <div className="flex items-center gap-2">
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
