"use client"

import { forwardRef, type CSSProperties } from "react"
import { GripVertical, PauseCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatBRL, formatTempoRelativo, nomeCliente } from "@/lib/formatters"
import type { AtendimentoListaItem } from "@/tipos/atendimentos"
import { corEstado, urgenciaLabel } from "@/components/atendimentos/utils"

export const KanbanCard = forwardRef<
  HTMLDivElement,
  {
    item: AtendimentoListaItem
    onClick: () => void
    dragHandleProps?: Record<string, unknown>
    isDragging?: boolean
    arrastavel?: boolean
    style?: CSSProperties
  }
>(function KanbanCard({ item, onClick, dragHandleProps, isDragging, arrastavel, style }, ref) {
  const cliente = nomeCliente(item.cliente.nome, item.cliente.telefone)
  const valorFinal = item.valor_final
  const valorExibido = valorFinal ?? item.valor_acordado

  return (
    <div
      ref={ref}
      style={style}
      {...dragHandleProps}
      className={cn(
        "relative rounded-lg border border-l-4 border-border bg-card p-3 shadow-elev-1 transition-all",
        arrastavel && "touch-none pl-7",
        corEstado(item.estado).faixa,
        isDragging
          ? "cursor-grabbing opacity-80 shadow-elev-2"
          : cn(
              arrastavel ? "cursor-grab" : "cursor-pointer",
              "hover:-translate-y-px hover:shadow-elev-2 hover:ring-1 hover:ring-border-brand/40"
            )
      )}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } }}
    >
      {arrastavel && (
        <span
          aria-hidden
          className="pointer-events-none absolute left-1 top-1/2 flex -translate-y-1/2 items-center rounded text-text-disabled"
        >
          <GripVertical size={14} strokeWidth={1.5} />
        </span>
      )}
      <div className="flex min-w-0 items-start justify-between gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-text-primary">{cliente}</p>
        <span className="shrink-0 font-mono text-[11px] text-text-muted">#{item.numero_curto}</span>
      </div>

      <p className="mt-0.5 truncate text-[11px] text-text-muted">{item.modelo.nome}</p>
      {item.programa_principal_nome && (
        <p className="mt-0.5 truncate text-[11px] text-text-secondary">
          {item.programa_principal_nome}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {item.urgencia === "imediato" && (
          <Badge variant="active" className="text-[10px]">
            {urgenciaLabel.imediato}
          </Badge>
        )}
        {item.urgencia && item.urgencia !== "imediato" && (
          <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium text-text-muted">
            {urgenciaLabel[item.urgencia]}
          </span>
        )}
        {item.ia_pausada && (
          <span className="flex items-center gap-1 text-[10px] font-medium text-text-secondary">
            <PauseCircle size={11} strokeWidth={1.5} />
            IA pausada
          </span>
        )}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        {valorExibido != null ? (
          <span className={cn(
            "text-[11px] font-medium tabular-nums",
            valorFinal != null ? "text-success-500" : "text-gold-500"
          )}>
            {formatBRL(Number(valorExibido))}
          </span>
        ) : (
          <span />
        )}
        <span className="text-[10px] tabular-nums text-text-disabled">{formatTempoRelativo(item.updated_at)}</span>
      </div>
    </div>
  )
})
