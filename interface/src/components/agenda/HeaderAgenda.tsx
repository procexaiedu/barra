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
  const ativos = bloqueios.filter((b) => b.estado === "bloqueado" || b.estado === "em_atendimento").length
  const emAtendimento = bloqueios.filter((b) => b.estado === "em_atendimento").length
  const cancelados = bloqueios.filter((b) => b.estado === "cancelado").length

  const hoje = dataInputSaoPaulo()
  const agora = new Date()
  const proximo = bloqueios
    .filter((b) => dataBrt(b.inicio) === hoje && b.estado === "bloqueado" && new Date(b.inicio) > agora)
    .sort((a, b) => a.inicio.localeCompare(b.inicio))[0] ?? null

  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
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

      <div className="flex flex-col items-end gap-3">
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
                    "rounded-md px-3 py-1 text-xs font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    visao === item.value
                      ? "bg-card text-text-brand shadow-sm"
                      : "text-text-muted hover:text-text-primary",
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
        )}

        {/* Painel de stats segmentado: uma superfície ancorada, divisores internos,
            cor reservada só ao número "ao vivo" (Em atendimento) — eco do ponto verde da grade. */}
        <dl className="flex shrink-0 divide-x divide-border overflow-hidden rounded-lg border border-border-strong bg-card">
          <ResumoItem label="Bloqueios ativos" value={ativos} />
          <ResumoItem label="Em atendimento" value={emAtendimento} live={emAtendimento > 0} />
          <ResumoItem label="Cancelados" value={cancelados} muted={cancelados === 0} />
        </dl>
      </div>
    </header>
  )
}

function ResumoItem({
  label,
  value,
  live = false,
  muted = false,
}: {
  label: string
  value: number
  live?: boolean
  muted?: boolean
}) {
  return (
    <div className="flex min-w-[6.5rem] flex-col gap-1 px-4 py-2.5">
      <dt className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {live && (
          <span
            className="size-1.5 rounded-full bg-success-500 motion-safe:animate-pulse"
            aria-hidden
          />
        )}
        {label}
      </dt>
      <dd
        className={cn(
          "font-mono text-2xl font-semibold leading-none tabular-nums",
          live ? "text-success-500" : muted ? "text-text-muted" : "text-text-primary",
        )}
      >
        {value}
      </dd>
    </div>
  )
}
