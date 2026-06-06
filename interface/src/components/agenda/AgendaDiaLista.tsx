"use client"

import { useMemo } from "react"
import { ChevronLeft, ChevronRight, Plus } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatHorario } from "@/lib/formatters"
import { estiloCardCompleto } from "@/components/agenda/cores"
import { dataBrt, dataDeInput, dataInput } from "@/hooks/useAgenda"
import type { BloqueioAgenda } from "@/tipos/agenda"

const ROTULO_TIPO: Record<string, string> = {
  interno: "Interno",
  externo: "Externo",
}

function deslocarDia(data: string, dir: -1 | 1): string {
  const d = dataDeInput(data)
  d.setDate(d.getDate() + dir)
  return dataInput(d)
}

function tituloBloco(b: BloqueioAgenda): string {
  return (
    b.atendimento?.cliente_nome ??
    b.observacao ??
    (b.atendimento_id ? "Agendamento" : "Bloqueio")
  )
}

/**
 * Versão mobile da agenda: lista vertical dos bloqueios de UM dia. Substitui a
 * GradeSemanal (grade de 7 dias com drag/resize, inviável em touch). Editar e
 * criar passam pelos diálogos já existentes — sem arrastar nem redimensionar.
 */
export function AgendaDiaLista({
  data,
  bloqueios,
  dataHoje,
  onNavegar,
  onHoje,
  onCriarNoDia,
  onEditar,
}: {
  data: string
  bloqueios: BloqueioAgenda[]
  dataHoje: string
  onNavegar: (novaData: string) => void
  onHoje: () => void
  onCriarNoDia: (data: string) => void
  onEditar: (b: BloqueioAgenda) => void
}) {
  const doDia = useMemo(
    () =>
      bloqueios
        .filter((b) => dataBrt(b.inicio) === data)
        .sort((a, b) => a.inicio.localeCompare(b.inicio)),
    [bloqueios, data]
  )

  const rotuloDia = useMemo(
    () =>
      new Intl.DateTimeFormat("pt-BR", {
        weekday: "short",
        day: "2-digit",
        month: "long",
        timeZone: "America/Sao_Paulo",
      }).format(dataDeInput(data)),
    [data]
  )

  const ehHoje = data === dataHoje

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between rounded-lg border border-border bg-card px-2 py-2">
        <button
          type="button"
          onClick={() => onNavegar(deslocarDia(data, -1))}
          aria-label="Dia anterior"
          className="flex size-9 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronLeft size={18} strokeWidth={1.5} />
        </button>
        <button
          type="button"
          onClick={onHoje}
          className={cn(
            "rounded-md px-3 py-1 text-sm font-medium capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            ehHoje ? "text-text-brand" : "text-text-primary hover:bg-accent"
          )}
        >
          {rotuloDia}
        </button>
        <button
          type="button"
          onClick={() => onNavegar(deslocarDia(data, 1))}
          aria-label="Próximo dia"
          className="flex size-9 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronRight size={18} strokeWidth={1.5} />
        </button>
      </div>

      <button
        type="button"
        onClick={() => onCriarNoDia(data)}
        className="flex h-10 items-center justify-center gap-1.5 rounded-lg border border-dashed border-border text-sm font-medium text-text-secondary transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Plus size={16} strokeWidth={1.5} />
        Novo bloqueio
      </button>

      {doDia.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-10 text-center text-sm text-text-muted">
          Nenhum bloqueio neste dia.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {doDia.map((b) => {
            const numCurto = b.atendimento?.numero_curto
            const tipo = b.atendimento?.tipo_atendimento
            const detalhes = [
              numCurto ? `#${numCurto}` : null,
              tipo ? ROTULO_TIPO[tipo] : null,
            ].filter(Boolean)
            return (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() => onEditar(b)}
                  className={cn(
                    "flex w-full flex-col gap-0.5 rounded-lg border border-border p-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    estiloCardCompleto(b)
                  )}
                >
                  <span className="font-mono text-sm tabular-nums text-text-primary">
                    {formatHorario(b.inicio)}–{formatHorario(b.fim)}
                  </span>
                  <span className="text-sm text-text-primary">{tituloBloco(b)}</span>
                  {detalhes.length > 0 && (
                    <span className="text-xs text-text-muted">{detalhes.join(" · ")}</span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
