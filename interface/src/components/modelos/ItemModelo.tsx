"use client"

import { Badge } from "@/components/ui/badge"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { ModeloListaItem } from "@/tipos/modelos"

const statusBadge = {
  ativa: { variant: "active" as const, label: "Ativa" },
  pausada: { variant: "paused" as const, label: "Pausada" },
  inativa: { variant: "lost" as const, label: "Inativa" },
}

export function ItemModelo({
  item,
  selected,
  onSelect,
}: {
  item: ModeloListaItem
  selected: boolean
  onSelect: () => void
}) {
  const badge = statusBadge[item.status]
  const handoff = item.indicadores.ultimo_handoff_em
    ? `ultima ajuda ${formatTempoRelativo(item.indicadores.ultimo_handoff_em)}`
    : "sem ajuda recente"

  return (
    <button
      type="button"
      role="button"
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect()
      }}
      className={cn(
        "w-full rounded-lg border border-border bg-card p-4 text-left transition-colors hover:bg-ink-200 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        selected && "border-l-3 border-l-gold-500",
        !selected && item.status === "pausada" && "border-l-3 border-l-ink-400",
        item.status === "inativa" && "opacity-60"
      )}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge variant={badge.variant}>{badge.label}</Badge>
        <span className={cn(
          "rounded-full bg-ink-300 px-3 py-1 text-xs font-medium",
          item.evolution_instance_id ? "text-text-muted" : "text-state-handoff"
        )}>
          {item.evolution_instance_id ? "WhatsApp pronto" : "WhatsApp pendente"}
        </span>
      </div>
      <p className="text-base font-semibold text-text-primary">{item.nome}</p>
      <p className="mt-1 font-mono text-xs text-text-muted">{formatTelefone(item.numero_whatsapp)}</p>
      <p className="mt-3 text-xs font-medium text-text-muted">
        {item.indicadores.atendimentos_abertos} abertos - {item.indicadores.conversas_ia_pausada} pausados - {handoff}
      </p>
    </button>
  )
}
