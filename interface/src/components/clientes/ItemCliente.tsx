"use client"

import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatBRL, formatTempoRelativo } from "@/lib/formatters"
import type { ClienteListaItem } from "@/tipos/clientes"

export function ItemCliente({
  item,
  selected,
  onSelect,
}: {
  item: ClienteListaItem
  selected: boolean
  onSelect: (id: string) => void
}) {
  const nome = item.nome ?? item.telefone_mascarado ?? "Sem nome"
  const refTempo = item.ultima_atividade

  const linha = [
    item.total_atendimentos > 0
      ? `${item.total_atendimentos} atend.`
      : "sem atendimentos",
    item.valor_total > 0 ? formatBRL(Number(item.valor_total)) : null,
    item.modelos_distintas > 1
      ? `${item.modelos_distintas} modelos`
      : item.modelo_predominante_nome
        ? `Modelo: ${item.modelo_predominante_nome}`
        : null,
  ]
    .filter(Boolean)
    .join(" · ")

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
        "cursor-pointer border-l-3 bg-card px-4 py-2.5 transition-all hover:bg-accent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        selected
          ? "bg-accent border-l-state-active [background-image:var(--gradient-gold-soft)]"
          : "border-l-transparent hover:border-l-border-subtle"
      )}
    >
      <div className="flex items-baseline gap-2">
        <p className="min-w-0 truncate text-sm">
          <span className="font-medium text-text-muted">Cliente:</span>{" "}
          <span className="font-semibold text-text-primary">{nome}</span>
        </p>
        {refTempo && (
          <span className="ml-auto shrink-0 text-xs text-text-muted">
            {formatTempoRelativo(refTempo)}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-2">
        {item.recorrente && (
          <Badge variant="paused" className="shrink-0">Recorrente</Badge>
        )}
        {item.total_atendimentos === 0 && (
          <span className="shrink-0 text-xs text-text-muted">novo</span>
        )}
        <p className="truncate text-xs text-text-muted">{linha}</p>
      </div>
    </article>
  )
}
