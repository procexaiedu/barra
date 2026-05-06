"use client"

import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { ConversaListaItem } from "@/tipos/clientes"
import { estadoAtendimentoLabel, motivoPerdaLabel } from "@/components/clientes/utils"

export function ItemConversa({
  item,
  selected,
  onSelect,
}: {
  item: ConversaListaItem
  selected: boolean
  onSelect: (id: string) => void
}) {
  const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
  const refTempo = item.ultima_mensagem_em ?? item.created_at
  const ultimo = item.ultimo_atendimento

  const linhaModelo = [
    item.modelo.nome,
    ultimo ? `#${ultimo.numero_curto}` : null,
    item.ultimo_motivo_perda
      ? `perda: ${motivoPerdaLabel[item.ultimo_motivo_perda].toLowerCase()}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ")

  const border = selected
    ? "border-l-state-active"
    : item.tem_atendimento_aberto
      ? "border-l-state-handoff"
      : "border-l-transparent"

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onSelect(item.id)
    }
  }

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => onSelect(item.id)}
      onKeyDown={handleKeyDown}
      className={cn(
        "cursor-pointer border-l-3 bg-card px-4 py-2.5 transition-colors hover:bg-ink-200",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        selected ? "bg-ink-200" : "",
        border
      )}
    >
      <div className="flex items-baseline gap-2">
        <p className="truncate text-base font-semibold text-text-primary">{cliente}</p>
        <span className="ml-auto shrink-0 text-xs text-text-muted">
          {formatTempoRelativo(refTempo)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        {item.recorrente && (
          <Badge variant="paused" className="shrink-0">Recorrente</Badge>
        )}
        {linhaModelo && (
          <p className="truncate text-xs text-text-muted">{linhaModelo}</p>
        )}
        {ultimo && (
          <span className="ml-auto shrink-0 text-xs text-text-muted">
            {estadoAtendimentoLabel[ultimo.estado]}
          </span>
        )}
      </div>
    </article>
  )
}
