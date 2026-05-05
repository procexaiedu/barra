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
    <header className="flex items-start justify-between gap-6">
      <div>
        <h1 className="font-serif text-[40px] leading-[48px] font-medium text-text-primary">
          Agenda
        </h1>
        <p className="text-sm text-text-muted">
          {modelo ? `Modelo ${modelo.nome}` : "Nenhuma modelo ativa"}
        </p>
        {proximo && (
          <p className="mt-1.5 text-sm text-text-muted">
            Próximo:{" "}
            <span className="font-medium text-text-primary">{formatHorario(proximo.inicio)}</span>
            {proximo.modelo_nome && (
              <span> · {proximo.modelo_nome.split(" ")[0]}</span>
            )}
            {proximo.atendimento && (
              <span>
                {" "}· {proximo.atendimento.cliente_nome ?? `#${proximo.atendimento.numero_curto}`}
              </span>
            )}
          </p>
        )}
      </div>
      <dl className="grid grid-cols-3 gap-3">
        <ResumoItem label="Bloqueios ativos" value={ativos} valueClass="text-sky-500" />
        <ResumoItem label="Em atendimento" value={emAtendimento} valueClass="text-emerald-500" />
        <ResumoItem label="Cancelados" value={cancelados} />
      </dl>
    </header>
  )
}

function ResumoItem({ label, value, valueClass }: { label: string; value: number; valueClass?: string }) {
  return (
    <div className="min-w-32 rounded-lg border border-border bg-card px-4 py-3">
      <dt className="text-xs font-medium text-text-muted">{label}</dt>
      <dd className={cn("mt-1 text-lg font-semibold", valueClass ?? "text-text-primary")}>{value}</dd>
    </div>
  )
}
