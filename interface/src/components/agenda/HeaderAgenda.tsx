import { Plus } from "lucide-react"
import { dataBrt, dataInputSaoPaulo } from "@/hooks/useAgenda"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { ModeloAgenda, BloqueioAgenda, VisaoAgenda } from "@/tipos/agenda"

const VISOES: Array<{ value: VisaoAgenda; label: string }> = [
  { value: "dia", label: "Dia" },
  { value: "semana", label: "Semana" },
  { value: "mes", label: "Mês" },
]

export function HeaderAgenda({
  modelo,
  bloqueios,
  visao,
  onVisaoChange,
  onCriar,
}: {
  modelo: ModeloAgenda | null
  bloqueios: BloqueioAgenda[]
  visao?: VisaoAgenda
  onVisaoChange?: (visao: VisaoAgenda) => void
  onCriar?: () => void
}) {
  const hoje = dataInputSaoPaulo()
  const agora = new Date()
  const proximo = bloqueios
    .filter((b) => dataBrt(b.inicio) === hoje && b.estado === "bloqueado" && new Date(b.inicio) > agora)
    .sort((a, b) => a.inicio.localeCompare(b.inicio))[0] ?? null

  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
          Agenda
        </h1>
        <p className="mt-1 text-[13px] text-text-muted">
          {modelo ? `Modelo ${modelo.nome}` : "Nenhuma modelo ativa"}
        </p>
        {proximo && (
          <p className="mt-1.5 flex items-center gap-1.5 text-sm text-text-muted">
            <span className="text-text-disabled">Próximo</span>
            <span className="font-mono font-medium tabular-nums text-text-primary">
              {formatHorario(proximo.inicio)}
            </span>
            {proximo.modelo_nome && (
              <span className="text-text-secondary">· {proximo.modelo_nome.split(" ")[0]}</span>
            )}
            {proximo.atendimento && (
              <span className="text-text-secondary">
                · {proximo.atendimento.cliente_nome ?? `#${proximo.atendimento.numero_curto}`}
              </span>
            )}
          </p>
        )}
      </div>

      {visao && onVisaoChange && (
        <div className="flex items-center gap-2">
          {/* Segmented (§7.9): poço recuado + aba ativa elevada (bg-card) com marca dourada */}
          <div className="flex rounded-lg border border-border bg-muted p-0.5" aria-label="Visão da agenda">
            {VISOES.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={visao === item.value}
                onClick={() => onVisaoChange(item.value)}
                className={cn(
                  "relative rounded-md px-3 py-1 text-xs font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  visao === item.value
                    ? "bg-card text-text-primary shadow-sm after:absolute after:inset-x-2 after:-bottom-px after:h-px after:rounded-full after:bg-gold-500"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          {onCriar && (
            <Button variant="primary" onClick={onCriar}>
              <Plus size={16} strokeWidth={1.5} />
              Novo
            </Button>
          )}
        </div>
      )}
    </header>
  )
}
