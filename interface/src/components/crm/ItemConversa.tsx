"use client"

import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { ConversaListaItem } from "@/tipos/crm"
import { estadoAtendimentoLabel, motivoPerdaLabel } from "@/components/crm/utils"

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
  const linhaModelo = [
    item.modelo.nome,
    item.ultimo_motivo_perda
      ? `perda: ${motivoPerdaLabel[item.ultimo_motivo_perda].toLowerCase()}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ")

  const ultimo = item.ultimo_atendimento

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
        "min-h-[88px] cursor-pointer border-l-3 bg-card px-4 py-3 transition-colors hover:bg-ink-200",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        selected ? "bg-ink-200" : "",
        border
      )}
    >
      <div className="flex items-center gap-2">
        {item.recorrente && <Badge variant="paused">Recorrente</Badge>}
        <span className="ml-auto text-xs font-medium text-text-muted">
          {formatTempoRelativo(refTempo)}
        </span>
      </div>
      <p className="mt-2 truncate text-base font-semibold text-text-primary">{cliente}</p>
      {linhaModelo && (
        <p className="truncate text-[13px] text-text-muted">{linhaModelo}</p>
      )}
      {ultimo && (
        <p className="mt-1 truncate text-xs font-medium text-text-muted">
          <span className="font-mono">#{ultimo.numero_curto}</span>{" "}
          {estadoAtendimentoLabel[ultimo.estado]} · {formatTempoRelativo(ultimo.created_at)}
        </p>
      )}
    </article>
  )
}
