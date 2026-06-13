import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda } from "@/tipos/agenda"

export function ToolbarAgenda({
  periodoLabel,
  modeloId,
  tipoAtendimento,
  bloqueios,
  onAnterior,
  onProximo,
  onHoje,
  onModeloChange,
  onTipoAtendimentoChange,
}: {
  periodoLabel: string
  modeloId: string | null
  tipoAtendimento: "" | "interno" | "externo" | "remoto"
  bloqueios: BloqueioAgenda[]
  onAnterior: () => void
  onProximo: () => void
  onHoje: () => void
  onModeloChange: (modeloId: string | null) => void
  onTipoAtendimentoChange: (tipo: "" | "interno" | "externo" | "remoto") => void
}) {
  const ativos = bloqueios.filter((b) => b.estado === "bloqueado" || b.estado === "em_atendimento").length
  const emAtendimento = bloqueios.filter((b) => b.estado === "em_atendimento").length
  const cancelados = bloqueios.filter((b) => b.estado === "cancelado").length

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-2">
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" onClick={onAnterior} aria-label="Período anterior">
          <ChevronLeft />
        </Button>
        <span className="min-w-0 flex-1 text-center text-sm font-semibold capitalize tabular-nums text-text-primary sm:min-w-44 sm:flex-none">
          {periodoLabel}
        </span>
        <Button variant="ghost" size="icon" onClick={onProximo} aria-label="Próximo período">
          <ChevronRight />
        </Button>
        <Button variant="outline" size="sm" onClick={onHoje} className="ml-1">
          Hoje
        </Button>
      </div>

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
            onChange={(e) => onTipoAtendimentoChange(e.target.value as "" | "interno" | "externo" | "remoto")}
            className="h-9 w-full appearance-none rounded-lg border border-input bg-input pl-3 pr-8 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">Todos</option>
            <option value="interno">Interno</option>
            <option value="externo">Externo</option>
            <option value="remoto">Vídeo chamada</option>
          </select>
          <ChevronDown
            size={14}
            strokeWidth={1.5}
            aria-hidden
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
        </div>
      </label>

      {/* Resumo de bloqueios: recolhido à direita da barra; cor reservada só ao
          número "ao vivo" (Em atendimento) — eco do ponto verde da grade. */}
      <dl className="flex w-full divide-x divide-border overflow-hidden rounded-lg border border-border bg-muted sm:ml-auto sm:w-auto sm:shrink-0">
        <ResumoItem label="Bloqueios ativos" value={ativos} />
        <ResumoItem label="Em atendimento" value={emAtendimento} live={emAtendimento > 0} />
        <ResumoItem label="Cancelados" value={cancelados} muted={cancelados === 0} />
      </dl>
    </div>
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
    <div className="flex min-w-0 flex-1 flex-col gap-0.5 px-3 py-1.5 sm:min-w-[6rem] sm:flex-none">
      <dt className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
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
          "font-mono text-lg font-semibold leading-none tabular-nums",
          live ? "text-success-500" : muted ? "text-text-muted" : "text-text-primary",
        )}
      >
        {value}
      </dd>
    </div>
  )
}
