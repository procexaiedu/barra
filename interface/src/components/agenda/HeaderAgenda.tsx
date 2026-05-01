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

  return (
    <header className="flex items-start justify-between gap-6">
      <div>
        <h1 className="font-serif text-[40px] leading-[48px] font-medium text-text-primary">
          Agenda
        </h1>
        <p className="text-sm text-text-muted">
          {modelo ? `Modelo ${modelo.nome}` : "Nenhuma modelo ativa"}
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-3">
        <ResumoItem label="Bloqueios ativos" value={ativos} />
        <ResumoItem label="Em atendimento" value={emAtendimento} />
        <ResumoItem label="Cancelados" value={cancelados} />
      </dl>
    </header>
  )
}

function ResumoItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-32 rounded-lg border border-border bg-card px-4 py-3">
      <dt className="text-xs font-medium text-text-muted">{label}</dt>
      <dd className="mt-1 text-lg font-semibold text-text-primary">{value}</dd>
    </div>
  )
}
