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
    ? `ajuda ${formatTempoRelativo(item.indicadores.ultimo_handoff_em)}`
    : "sem ajuda recente"
  const wppPendente = item.evolution_status !== "conectado"
  const wppPareando = item.evolution_status === "pareando"

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
        "group relative w-full px-3 py-2.5 text-left transition-colors hover:bg-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "border-l-[3px] border-l-transparent",
        selected && "bg-ink-100 border-l-gold-500",
        item.status === "inativa" && "opacity-60"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={cn(
          "truncate text-sm font-semibold",
          selected ? "text-text-primary" : "text-text-primary"
        )}>
          {item.nome}
        </span>
        <Badge variant={badge.variant} className="shrink-0 px-2 py-0.5 text-[11px]">
          {badge.label}
        </Badge>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-text-muted">
        <span className="font-mono">{formatTelefone(item.numero_whatsapp)}</span>
        {wppPendente && (
          <span className={wppPareando ? "text-state-info" : "text-state-handoff"}>
            {wppPareando ? "Pareando…" : "WhatsApp pendente"}
          </span>
        )}
      </div>
      <div className="mt-1 text-[11px] text-text-muted">
        {item.indicadores.atendimentos_abertos > 0 && (
          <span className="text-text-secondary">{item.indicadores.atendimentos_abertos} aberto{item.indicadores.atendimentos_abertos > 1 ? "s" : ""}</span>
        )}
        {item.indicadores.atendimentos_abertos > 0 && " · "}
        {item.indicadores.conversas_ia_pausada > 0 && (
          <>
            <span className="text-state-handoff">{item.indicadores.conversas_ia_pausada} pausado{item.indicadores.conversas_ia_pausada > 1 ? "s" : ""}</span>
            {" · "}
          </>
        )}
        <span>{handoff}</span>
      </div>
    </button>
  )
}
