"use client"

import { PauseCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { formatBRL, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { AtendimentoListaItem } from "@/tipos/atendimentos"
import { badgeForEstado, urgenciaLabel } from "@/components/atendimentos/utils"

export function KanbanCard({
  item,
  onClick,
  dragHandleProps,
  isDragging,
}: {
  item: AtendimentoListaItem
  onClick: () => void
  dragHandleProps?: Record<string, unknown>
  isDragging?: boolean
}) {
  const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
  const valorExibido = item.valor_final ?? item.valor_acordado

  return (
    <div
      className={`rounded-lg border border-border bg-card p-3 transition-shadow ${isDragging ? "shadow-lg opacity-80 cursor-grabbing" : "cursor-pointer hover:border-ring/40 hover:shadow-sm"}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } }}
      {...dragHandleProps}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">{cliente}</p>
        <span className="shrink-0 font-mono text-[11px] text-text-disabled">#{item.numero_curto}</span>
      </div>

      <p className="mt-0.5 truncate text-[11px] text-text-muted">{item.modelo.nome}</p>
      {item.programa_principal_nome && (
        <p className="mt-0.5 truncate text-[11px] text-text-secondary">
          {item.programa_principal_nome}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {item.urgencia === "imediato" && (
          <Badge variant={badgeForEstado(item.estado)} className="text-[10px]">
            {urgenciaLabel.imediato}
          </Badge>
        )}
        {item.urgencia && item.urgencia !== "imediato" && (
          <Badge variant="active" className="text-[10px] opacity-60">
            {urgenciaLabel[item.urgencia]}
          </Badge>
        )}
        {item.ia_pausada && (
          <span className="flex items-center gap-1 text-[10px] text-state-handoff">
            <PauseCircle size={11} strokeWidth={1.5} />
            IA pausada
          </span>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        {valorExibido != null ? (
          <span className="text-[11px] font-medium text-success-500">
            {formatBRL(Number(valorExibido))}
          </span>
        ) : (
          <span />
        )}
        <span className="text-[10px] text-text-disabled">{formatTempoRelativo(item.updated_at)}</span>
      </div>
    </div>
  )
}
