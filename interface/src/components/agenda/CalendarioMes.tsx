"use client"

import { useState } from "react"
import { X } from "lucide-react"
import { BloqueioAgenda } from "@/components/agenda/BloqueioAgenda"
import { dataBrt, dataDeInput, dataInput } from "@/hooks/useAgenda"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioAgendaTipo, VisaoAgenda } from "@/tipos/agenda"

const diasSemana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

function mesmoDia(iso: string, data: string) {
  return dataBrt(iso) === data
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
  const ultimo = new Date(base.getFullYear(), base.getMonth() + 1, 0)

  const inicio = new Date(primeiro)
  const diaSemana = inicio.getDay()
  const deslocamento = diaSemana === 0 ? -6 : 1 - diaSemana
  inicio.setDate(inicio.getDate() + deslocamento)

  // Mínimo de semanas para cobrir todos os dias do mês (5 ou 6)
  const diasAteUltimo = (ultimo.getTime() - inicio.getTime()) / (1000 * 60 * 60 * 24) + 1
  const total = Math.min(Math.max(Math.ceil(diasAteUltimo / 7) * 7, 35), 42)

  return Array.from({ length: total }, (_, i) => {
    const item = new Date(inicio)
    item.setDate(inicio.getDate() + i)
    return item
  })
}

function formatarDataPainel(data: string): string {
  const d = dataDeInput(data)
  return d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" })
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
  // Armazena o mês junto ao dia para que o painel se feche automaticamente ao navegar de mês
  const [painelState, setPainelState] = useState<{ data: string; mes: string } | null>(null)

  const dias = diasParaVisao(visao, dataSelecionada)
  const mesBase = dataDeInput(dataSelecionada).getMonth()
  const mesAtual = dataSelecionada.slice(0, 7)

  // Painel só é válido enquanto o usuário está no mesmo mês em que foi aberto
  const diaPainel = painelState?.mes === mesAtual ? painelState.data : null

  const bloqueiosPainel = diaPainel
    ? bloqueios.filter((b) => mesmoDia(b.inicio, diaPainel))
    : []

  return (
    <section aria-label="Calendário mensal" className="flex min-w-0 gap-3 rounded-lg border border-border bg-card p-4">
      <div className="min-w-0 flex-1">
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
            const painelAberto = data === diaPainel
            const foraDoMes = visao === "mes" && dia.getMonth() !== mesBase
            const bloqueiosDia = bloqueios.filter((b) => mesmoDia(b.inicio, data))
            const visiveis = bloqueiosDia.slice(0, 2)
            const overflow = bloqueiosDia.length - visiveis.length
            return (
              <div
                key={data}
                role="button"
                tabIndex={0}
                onClick={() => onSelecionarDia(data)}
                onDoubleClick={() => onCriarNoDia(data)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    onSelecionarDia(data)
                  }
                }}
                className={cn(
                  "min-h-[clamp(6rem,9vw,8rem)] rounded-lg border border-border bg-background p-2 text-left transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
                  selecionado && "border-ring",
                  painelAberto && !selecionado && "border-ring/50",
                  foraDoMes && "opacity-45",
                  visao === "dia" && "min-h-[420px]"
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-1">
                  <span className={cn("text-sm font-semibold", selecionado ? "text-text-brand" : "text-text-primary")}>
                    {dia.getDate()}
                  </span>
                  {overflow > 0 && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        setPainelState(painelAberto ? null : { data, mes: mesAtual })
                      }}
                      className="rounded px-1 py-0.5 text-[10px] font-medium text-text-muted hover:bg-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      +{overflow} mais
                    </button>
                  )}
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
      </div>

      {diaPainel && (
        <aside className="w-72 shrink-0 rounded-lg border border-border bg-background">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold capitalize text-text-primary">
              {formatarDataPainel(diaPainel)}
            </span>
            <button
              type="button"
              onClick={() => setPainelState(null)}
              aria-label="Fechar painel"
              className="rounded p-1 text-text-muted hover:bg-muted hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X size={13} />
            </button>
          </div>
          <div className="max-h-[32rem] space-y-2 overflow-y-auto p-2">
            {bloqueiosPainel.length === 0 ? (
              <p className="py-2 text-center text-xs text-text-muted">Nenhum bloqueio neste dia.</p>
            ) : (
              bloqueiosPainel.map((bloqueio) => (
                <BloqueioAgenda
                  key={bloqueio.id}
                  bloqueio={bloqueio}
                  compacto
                  onClick={() => {
                    onEditarBloqueio(bloqueio)
                    setPainelState(null)
                  }}
                />
              ))
            )}
          </div>
        </aside>
      )}
    </section>
  )
}
