"use client"

import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatBRL, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { AtendimentoListaItem } from "@/tipos/atendimentos"
import { badgeForEstado, estadoLabel, sinaisParaTipo, tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"

export function ItemAtendimento({
  item,
  selected,
  onSelect,
}: {
  item: AtendimentoListaItem
  selected: boolean
  onSelect: (id: string) => void
}) {
  const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
  const valorFinal = item.valor_final
  const valorExibido = valorFinal ?? item.valor_acordado
  const sq = item.sinais_qualificacao as Record<string, unknown> | null | undefined
  const sinais = sinaisParaTipo(item.tipo_atendimento)
  const progresso = sq
    ? sinais.filter(({ chave }) => sq[chave] === true).length
    : null
  const pct = progresso !== null && sinais.length > 0 ? Math.round((progresso / sinais.length) * 100) : null
  const meta = [
    item.modelo.nome,
    `#${item.numero_curto}`,
    item.tipo_atendimento ? tipoLabel[item.tipo_atendimento] : null,
    item.urgencia ? urgenciaLabel[item.urgencia] : null,
    item.programa_principal_nome,
    pct !== null ? `${pct}%` : null,
  ]
    .filter(Boolean)
    .join(" · ")
  const border = selected
    ? "border-l-state-active"
    : item.ia_pausada
      ? "border-l-state-handoff"
      : "border-l-transparent hover:border-l-border-brand/50"

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
        "cursor-pointer border-l-4 bg-card px-4 py-3 transition-colors",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        selected ? "bg-accent" : "hover:bg-surface-hover",
        border
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <p className="flex-1 truncate text-sm font-semibold text-text-primary">{cliente}</p>
        <Badge variant={badgeForEstado(item.estado)} className="shrink-0">{estadoLabel[item.estado]}</Badge>
        <span className="shrink-0 text-xs font-medium tabular-nums text-text-muted">
          {formatTempoRelativo(item.updated_at)}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <p className="min-w-0 flex-1 truncate text-xs text-text-muted">{meta}</p>
        {valorExibido != null && (
          <span
            className={cn(
              "shrink-0 text-xs font-medium tabular-nums",
              valorFinal != null ? "text-success-500" : "text-gold-500"
            )}
          >
            {formatBRL(Number(valorExibido))}
          </span>
        )}
      </div>
    </article>
  )
}
