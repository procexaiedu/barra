"use client"

import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Circle,
  CreditCard,
  DoorOpen,
  Pause,
  Play,
  Sparkles,
  XCircle,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatHorario } from "@/lib/formatters"
import type { EventoAtendimento } from "@/tipos/atendimentos"
import {
  autorEventoLabel,
  categoriaEvento,
  descricaoEvento,
  iconeEvento,
  tipoEventoLabel,
} from "@/components/atendimentos/utils"

const ICONES: Record<string, LucideIcon> = {
  estado: ArrowRight,
  ia: Sparkles,
  pix: CreditCard,
  fechado: CheckCircle2,
  perdido: XCircle,
  chegada: DoorOpen,
  pausa: Pause,
  retomada: Play,
  bloqueio: CalendarClock,
  default: Circle,
}

export function LinhaEvento({ evento, isLast }: { evento: EventoAtendimento; isLast?: boolean }) {
  const Icone = ICONES[iconeEvento(evento.tipo)] ?? Circle
  const descricao = descricaoEvento(evento)
  const autor = autorEventoLabel(evento.autor)
  const telemetria = categoriaEvento(evento.tipo) === "telemetria"

  return (
    <li className="relative flex gap-3">
      {/* Trilho vertical conectando os itens (omitido no último) */}
      {!isLast && (
        <span aria-hidden className="absolute bottom-0 left-[11px] top-6 w-px bg-border" />
      )}
      <span
        className={cn(
          "z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full ring-1",
          telemetria
            ? "bg-muted text-text-muted ring-border-subtle"
            : "bg-accent text-text-secondary ring-border"
        )}
      >
        <Icone size={13} strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1 pb-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="text-[13px] font-medium text-text-primary">
            {tipoEventoLabel(evento.tipo)}
          </span>
          {autor && <span className="text-[11px] text-text-muted">{autor}</span>}
          <span className="ml-auto text-[11px] tabular-nums text-text-muted">
            {formatHorario(evento.created_at)}
          </span>
        </div>
        {descricao && (
          <p className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-text-secondary">{descricao}</p>
        )}
      </div>
    </li>
  )
}
