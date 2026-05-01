"use client"

import { Badge } from "@/components/ui/badge"
import { formatBRL, formatData } from "@/lib/formatters"
import type { AtendimentoHistoricoItem } from "@/tipos/crm"
import { badgeForEstado, estadoAtendimentoLabel, motivoPerdaLabel, truncar } from "@/components/crm/utils"

export function ItemAtendimentoHistorico({ item }: { item: AtendimentoHistoricoItem }) {
  const detalheFinal =
    item.estado === "Fechado" && item.valor_final !== null
      ? formatBRL(Number(item.valor_final))
      : item.estado === "Perdido" && item.motivo_perda
        ? item.motivo_perda === "outro" && item.motivo_perda_obs
          ? truncar(item.motivo_perda_obs, 40)
          : motivoPerdaLabel[item.motivo_perda]
        : null

  return (
    <div className="flex h-14 items-center gap-3 px-4">
      <span className="font-mono text-xs text-text-muted">#{item.numero_curto}</span>
      <Badge variant={badgeForEstado(item.estado)}>{estadoAtendimentoLabel[item.estado]}</Badge>
      <span className="text-sm text-text-primary">{formatData(item.created_at)}</span>
      {detalheFinal && (
        <>
          <span className="text-text-muted">·</span>
          <span className="text-sm text-text-primary">{detalheFinal}</span>
        </>
      )}
    </div>
  )
}
