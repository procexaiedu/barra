import { Plus } from "lucide-react"
import { BloqueioAgenda } from "@/components/agenda/BloqueioAgenda"
import { formatData } from "@/lib/formatters"
import type { BloqueioAgenda as BloqueioAgendaTipo } from "@/tipos/agenda"

const horas = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`)

function dataIso(data: string) {
  return `${data}T12:00:00-03:00`
}

function horaBrt(iso: string): string {
  const partes = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso))
  const h = partes.find((p) => p.type === "hour")?.value ?? "00"
  const m = partes.find((p) => p.type === "minute")?.value ?? "00"
  return `${h.padStart(2, "0")}:${m.padStart(2, "0")}`
}

export function PainelDia({
  dataSelecionada,
  bloqueios,
  onCriarSlot,
  onEditarBloqueio,
}: {
  dataSelecionada: string
  bloqueios: BloqueioAgendaTipo[]
  onCriarSlot: (horario: string) => void
  onEditarBloqueio: (bloqueio: BloqueioAgendaTipo) => void
}) {
  const porHora = new Map(bloqueios.map((b) => [horaBrt(b.inicio), b]))
  const vazio = bloqueios.length === 0

  return (
    <section aria-label="Dia selecionado" className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-text-primary capitalize">
          {formatData(dataIso(dataSelecionada))}
        </h2>
        <p className="text-sm text-text-muted">
          {bloqueios.length} {bloqueios.length === 1 ? "bloqueio" : "bloqueios"}
        </p>
      </div>
      {vazio && (
        <div className="mb-3 rounded-lg border border-border bg-background p-3">
          <p className="text-sm font-medium text-text-primary">Dia livre.</p>
          <p className="text-sm text-text-muted">Clique em um horário para bloqueá-lo.</p>
        </div>
      )}
      <div className="max-h-[calc(100vh-280px)] space-y-2 overflow-y-auto pr-1">
        {horas.map((hora) => {
          const bloqueio = porHora.get(hora)
          if (bloqueio) {
            return (
              <BloqueioAgenda
                key={hora}
                bloqueio={bloqueio}
                onClick={() => onEditarBloqueio(bloqueio)}
              />
            )
          }
          return (
            <button
              key={hora}
              type="button"
              onClick={() => onCriarSlot(hora)}
              className="flex h-11 w-full items-center justify-between rounded-lg border border-border bg-background px-3 text-left text-sm text-text-muted transition-colors hover:bg-muted hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
            >
              <span className="font-mono text-xs">{hora}</span>
              <Plus size={16} strokeWidth={1.5} />
            </button>
          )
        })}
      </div>
    </section>
  )
}
