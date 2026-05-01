import { BloqueioAgenda } from "@/components/agenda/BloqueioAgenda"
import { dataDeInput, dataInput } from "@/hooks/useAgenda"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioAgendaTipo, VisaoAgenda } from "@/tipos/agenda"

const diasSemana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

function mesmoDia(iso: string, data: string) {
  return iso.slice(0, 10) === data
}

function diasParaVisao(visao: VisaoAgenda, dataSelecionada: string) {
  const base = dataDeInput(dataSelecionada)
  if (visao === "dia") return [base]
  if (visao === "semana") {
    const d = new Date(base)
    const dia = d.getDay()
    const deslocamento = dia === 0 ? -6 : 1 - dia
    d.setDate(d.getDate() + deslocamento)
    return Array.from({ length: 7 }, (_, i) => {
      const item = new Date(d)
      item.setDate(d.getDate() + i)
      return item
    })
  }

  const primeiro = new Date(base.getFullYear(), base.getMonth(), 1)
  const inicio = new Date(primeiro)
  const dia = inicio.getDay()
  const deslocamento = dia === 0 ? -6 : 1 - dia
  inicio.setDate(inicio.getDate() + deslocamento)
  return Array.from({ length: 42 }, (_, i) => {
    const item = new Date(inicio)
    item.setDate(inicio.getDate() + i)
    return item
  })
}

export function CalendarioMes({
  visao,
  dataSelecionada,
  bloqueios,
  onSelecionarDia,
  onCriarNoDia,
  onEditarBloqueio,
}: {
  visao: VisaoAgenda
  dataSelecionada: string
  bloqueios: BloqueioAgendaTipo[]
  onSelecionarDia: (data: string) => void
  onCriarNoDia: (data: string) => void
  onEditarBloqueio: (bloqueio: BloqueioAgendaTipo) => void
}) {
  const dias = diasParaVisao(visao, dataSelecionada)
  const mesBase = dataDeInput(dataSelecionada).getMonth()

  return (
    <section aria-label="Calendário mensal" className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="grid grid-cols-7 gap-2 pb-2">
        {diasSemana.map((dia) => (
          <div key={dia} className="px-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            {dia}
          </div>
        ))}
      </div>
      <div className={cn("grid grid-cols-7 gap-2", visao === "dia" && "grid-cols-1", visao === "semana" && "grid-cols-7")}>
        {dias.map((dia) => {
          const data = dataInput(dia)
          const selecionado = data === dataSelecionada
          const foraDoMes = visao === "mes" && dia.getMonth() !== mesBase
          const bloqueiosDia = bloqueios.filter((b) => mesmoDia(b.inicio, data))
          const visiveis = bloqueiosDia.slice(0, 3)
          const overflow = bloqueiosDia.length - visiveis.length
          return (
            <div
              key={data}
              role="button"
              tabIndex={0}
              onClick={() => onSelecionarDia(data)}
              onDoubleClick={() => {
                if (bloqueiosDia.length === 0) onCriarNoDia(data)
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  onSelecionarDia(data)
                }
              }}
              className={cn(
                "min-h-[clamp(7rem,12vw,11rem)] rounded-lg border border-border bg-background p-2 text-left transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
                selecionado && "border-ring",
                foraDoMes && "opacity-45",
                visao === "dia" && "min-h-[420px]"
              )}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className={cn("text-sm font-semibold", selecionado ? "text-text-brand" : "text-text-primary")}>
                  {dia.getDate()}
                </span>
                {overflow > 0 && <span className="text-xs text-text-muted">+{overflow}</span>}
              </div>
              <div className="space-y-1">
                {visiveis.map((bloqueio) => (
                  <BloqueioAgenda
                    key={bloqueio.id}
                    bloqueio={bloqueio}
                    compacto
                    onClick={() => onEditarBloqueio(bloqueio)}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
