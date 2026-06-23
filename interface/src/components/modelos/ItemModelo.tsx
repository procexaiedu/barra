"use client"

import { Badge } from "@/components/ui/badge"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import { rotuloPerfil } from "@/lib/perfilFisico"
import { NIVEL_BADGE_CLASS, NIVEL_LABEL } from "@/lib/nivel"
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
        "group relative w-full rounded-lg border border-border bg-card px-3 py-2.5 text-left shadow-elev-1 transition-all hover:-translate-y-px hover:bg-surface-hover hover:shadow-elev-2 hover:ring-1 hover:ring-border-brand/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] before:rounded-l-lg before:bg-transparent",
        selected && "bg-accent before:bg-gold-500 ring-1 ring-border-brand/40",
        item.status === "inativa" && "opacity-60"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-text-primary">
          {item.nome}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {item.nivel && (
            <span
              className={cn(
                "inline-flex size-[18px] items-center justify-center rounded-full border text-[10px] font-semibold",
                NIVEL_BADGE_CLASS[item.nivel]
              )}
              title={`Nível ${NIVEL_LABEL[item.nivel]}`}
            >
              {NIVEL_LABEL[item.nivel]}
            </span>
          )}
          <Badge variant={badge.variant} className="px-2 py-0.5 text-[11px]">
            {badge.label}
          </Badge>
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-text-muted">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="font-mono">{formatTelefone(item.numero_whatsapp)}</span>
          {item.tipo_fisico && (
            <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[10px] text-text-secondary">
              {rotuloPerfil(item.tipo_fisico)}
            </span>
          )}
        </span>
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
