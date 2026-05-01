"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { formatDataHora } from "@/lib/formatters"
import type { EventoAtendimento } from "@/tipos/atendimentos"
import { resumoPayload } from "@/components/atendimentos/utils"

export function LinhaEvento({ evento }: { evento: EventoAtendimento }) {
  const [aberto, setAberto] = useState(false)
  const payload = resumoPayload(evento.payload)

  return (
    <article className="border-b border-border py-3 last:border-b-0">
      <div className="flex items-start gap-3">
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={aberto ? "Recolher detalhes" : "Expandir detalhes"}
          onClick={() => setAberto((value) => !value)}
        >
          {aberto ? <ChevronDown size={14} strokeWidth={1.5} /> : <ChevronRight size={14} strokeWidth={1.5} />}
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-medium text-text-primary">{evento.tipo.replaceAll("_", " ")}</span>
            <span className="text-xs text-text-muted">{evento.origem}</span>
            <span className="text-xs text-text-muted">·</span>
            <span className="text-xs text-text-muted">{evento.autor}</span>
            <span className="ml-auto text-xs text-text-muted">{formatDataHora(evento.created_at)}</span>
          </div>
          <p className="mt-1 line-clamp-1 text-[13px] text-text-secondary">{payload}</p>
          {aberto && (
            <pre className="mt-2 max-h-52 overflow-auto rounded-md bg-ink-200 p-3 font-mono text-xs text-text-muted">
              {JSON.stringify(evento.payload, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </article>
  )
}
