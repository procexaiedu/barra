"use client"

import { Badge } from "@/components/ui/badge"
import { formatBRL, formatData } from "@/lib/formatters"
import type { AtendimentoHistoricoItem } from "@/tipos/clientes"
import {
  badgeForEstado,
  estadoAtendimentoLabel,
  formaPagamentoLabel,
  motivoPerdaLabel,
  truncar,
} from "@/components/clientes/utils"
import { tipoLabel } from "@/components/atendimentos/utils"

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

  const contexto = [
    item.tipo_atendimento ? tipoLabel[item.tipo_atendimento] : null,
    item.programa?.nome ?? null,
    item.duracao?.nome ?? null,
    item.estado === "Fechado" && item.forma_pagamento
      ? formaPagamentoLabel[item.forma_pagamento]
      : null,
  ].filter(Boolean)

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-14 w-full flex-col items-start gap-1 px-4 py-3 text-left
                 hover:bg-surface-hover focus-visible:outline-none
                 focus-visible:ring-inset focus-visible:ring-2 focus-visible:ring-ring
                 transition-colors"
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-text-muted">#{item.numero_curto}</span>
        <Badge variant={badgeForEstado(item.estado)}>{estadoAtendimentoLabel[item.estado]}</Badge>
        <span className="text-xs text-text-muted">{formatData(item.created_at)}</span>
        {detalheFinal && (
          <>
            <span className="text-text-muted">·</span>
            <span
              className={
                item.estado === "Fechado"
                  ? "text-sm font-medium text-state-won"
                  : "text-xs text-text-muted"
              }
            >
              {detalheFinal}
            </span>
          </>
        )}
      </div>
      {contexto.length > 0 && (
        <div className="text-[12px] text-text-secondary">{contexto.join(" · ")}</div>
      )}
    </button>
  )
}
