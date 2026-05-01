"use client"

import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatBRL, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { PixListaItem } from "@/tipos/pix"
import { badgeForStatusPix, motivoRevisaoLabel, statusItemPix } from "./utils"

export function ItemPix({
  item,
  selected,
  onSelect,
}: {
  item: PixListaItem
  selected: boolean
  onSelect: (id: string) => void
}) {
  const status = statusItemPix(item.decisao_pipeline, item.decisao_final)
  const badge = badgeForStatusPix(status)
  const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
  const meta = [
    cliente,
    item.modelo.nome,
    item.atendimento ? `#${item.atendimento.numero_curto}` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  const border = selected
    ? "border-l-state-active"
    : status === "em_revisao"
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
        <Badge variant={badge.variant}>{badge.label}</Badge>
        <span className="ml-auto text-xs font-medium text-text-muted">
          {formatTempoRelativo(item.created_at)}
        </span>
      </div>
      <p className="mt-2 text-base font-semibold text-text-primary">
        {item.valor_extraido !== null
          ? formatBRL(item.valor_extraido)
          : <span className="text-text-muted">Valor não extraído</span>}
      </p>
      <p className="truncate text-[13px] text-text-muted">{meta}</p>
      {status === "em_revisao" && item.motivo_em_revisao && (
        <p className="mt-1 truncate text-[13px] text-text-muted">
          {motivoRevisaoLabel[item.motivo_em_revisao]}
        </p>
      )}
    </article>
  )
}
