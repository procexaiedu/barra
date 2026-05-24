"use client"

import { AlertTriangle } from "lucide-react"
import { formatHorario, formatTelefone } from "@/lib/formatters"
import type { BloqueioAgenda } from "@/tipos/agenda"

const DIA_MES_FMT = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
})

function periodoLegivel(inicio: string, fim: string): string {
  return `${DIA_MES_FMT.format(new Date(inicio))} ${formatHorario(inicio)}–${formatHorario(fim)}`
}

function clienteLegivel(bloqueio: BloqueioAgenda): string | null {
  const at = bloqueio.atendimento
  if (!at) return null
  const nome = at.cliente_nome ?? formatTelefone(at.cliente_telefone_formatado)
  return `#${at.numero_curto} · ${nome}`
}

export function AlertaConflito({ conflitos }: { conflitos: BloqueioAgenda[] }) {
  if (conflitos.length === 0) return null

  return (
    <div className="rounded-lg border border-state-lost/40 bg-state-lost/10 px-3 py-2.5 text-xs">
      <div className="flex items-center gap-1.5 font-medium text-state-lost">
        <AlertTriangle size={14} strokeWidth={2} />
        <span>
          {conflitos.length === 1
            ? "Conflito de agenda neste horário"
            : `${conflitos.length} conflitos de agenda neste horário`}
        </span>
      </div>
      <ul className="mt-1.5 space-y-1 text-text-secondary">
        {conflitos.map((b) => {
          const cliente = clienteLegivel(b)
          return (
            <li key={b.id} className="leading-snug">
              <span className="text-text-primary">{b.modelo_nome ?? "Modelo"}</span>
              {" · "}
              {periodoLegivel(b.inicio, b.fim)}
              {cliente && <span className="text-text-muted">{` · ${cliente}`}</span>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
