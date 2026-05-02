"use client"

import { formatDataHora } from "@/lib/formatters"
import type { EventoAtendimento } from "@/tipos/atendimentos"
import {
  autorEventoLabel,
  origemEventoLabel,
  resumoPayload,
  tipoEventoLabel,
} from "@/components/atendimentos/utils"

export function LinhaEvento({ evento }: { evento: EventoAtendimento }) {
  const resumo = resumoPayload(evento.payload)
  const origem = origemEventoLabel(evento.origem)
  const autor = autorEventoLabel(evento.autor)
  const mostraAutor = autor && autor !== origem

  return (
    <article className="border-b border-border py-2 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-medium text-text-primary">
            {tipoEventoLabel(evento.tipo)}
          </span>
          <span className="text-xs text-text-muted">{origem}</span>
          {mostraAutor && (
            <>
              <span className="text-xs text-text-muted">·</span>
              <span className="text-xs text-text-muted">{autor}</span>
            </>
          )}
          <span className="ml-auto text-xs text-text-muted">{formatDataHora(evento.created_at)}</span>
        </div>
        {resumo && (
          <p className="mt-1 line-clamp-2 text-[13px] text-text-secondary">{resumo}</p>
        )}
      </div>
    </article>
  )
}
