import { dataBrt, dataInputSaoPaulo } from "@/hooks/useAgenda"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { ModeloAgenda, BloqueioAgenda } from "@/tipos/agenda"

export function HeaderAgenda({
  modelo,
  bloqueios,
}: {
  modelo: ModeloAgenda | null
  bloqueios: BloqueioAgenda[]
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
        <h1 className="font-serif text-[26px] leading-8 font-medium text-text-primary">
          Agenda
        </h1>
        <p className="text-sm text-text-muted">
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

      {/* Painel de stats segmentado: uma superfície ancorada, divisores internos,
          cor reservada só ao número "ao vivo" (Em atendimento) — eco do ponto verde da grade. */}
      <dl className="flex shrink-0 divide-x divide-border overflow-hidden rounded-lg border border-border-strong bg-card">
        <ResumoItem label="Bloqueios ativos" value={ativos} />
        <ResumoItem label="Em atendimento" value={emAtendimento} live={emAtendimento > 0} />
        <ResumoItem label="Cancelados" value={cancelados} muted={cancelados === 0} />
      </dl>
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
      <dt className="flex items-center gap-1.5 text-xs font-medium text-text-muted">
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
          "text-2xl font-semibold leading-none tabular-nums",
          live ? "text-success-500" : muted ? "text-text-muted" : "text-text-primary",
        )}
      >
        {value}
      </dd>
    </div>
  )
}
