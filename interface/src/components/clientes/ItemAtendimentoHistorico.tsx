"use client"

import { Badge } from "@/components/ui/badge"
import { formatBRL, formatData } from "@/lib/formatters"
import type { AtendimentoHistoricoItem } from "@/tipos/clientes"
import { badgeForEstado, estadoAtendimentoLabel, motivoPerdaLabel, truncar } from "@/components/clientes/utils"

export function ItemAtendimentoHistorico({
  item,
  onClick,
}: {
  item: AtendimentoHistoricoItem
  onClick: () => void
}) {
  const detalheFinal =
    item.estado === "Fechado" && item.valor_final !== null
      ? formatBRL(Number(item.valor_final))
      : item.estado === "Perdido" && item.motivo_perda
        ? item.motivo_perda === "outro" && item.motivo_perda_obs
          ? truncar(item.motivo_perda_obs, 40)
          : motivoPerdaLabel[item.motivo_perda]
        : null

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-14 w-full items-center gap-3 px-4 text-left
                 hover:bg-surface-hover focus-visible:outline-none
                 focus-visible:ring-inset focus-visible:ring-2 focus-visible:ring-ring
                 transition-colors"
    >
      <span className="font-mono text-xs text-text-muted">#{item.numero_curto}</span>
      <Badge variant={badgeForEstado(item.estado)}>{estadoAtendimentoLabel[item.estado]}</Badge>
      <span className="text-xs text-text-muted">{formatData(item.created_at)}</span>
      {detalheFinal && (
        <>
          <span className="text-text-muted">·</span>
          <span className={item.estado === "Fechado" ? "text-sm font-medium text-state-won" : "text-xs text-text-muted"}>
            {detalheFinal}
          </span>
        </>
      )}
    </button>
  )
}
