"use client"

import { useMemo } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import type {
  FinanceiroResumo,
  FinanceiroResumoResponse,
  FinanceiroSerieDia,
  FinanceiroSerieResponse,
} from "@/tipos/financeiro"
import { KpiCard } from "./KpiCard"
import { StatusRepasses } from "./StatusRepasses"
import { ChartReceitaDiaria } from "./charts/ChartReceitaDiaria"
import { ChartTopModelos } from "./charts/ChartTopModelos"
import { ChartMixForma } from "./charts/ChartMixForma"

interface SeriesSpark {
  bruto: number[]
  liquido: number[]
  fechamentos: number[]
  ticket: number[]
  rotulos: string[]
}

const FMT_DIA_TOOLTIP = new Intl.DateTimeFormat("pt-BR", {
  weekday: "short",
  day: "2-digit",
  month: "short",
  timeZone: "America/Sao_Paulo",
})

function derivarSparklines(serie: FinanceiroSerieDia[]): SeriesSpark {
  // Serie pode chegar curta; o Sparkline trata <2 pontos sozinho.
  return serie.reduce<SeriesSpark>(
    (acc, d) => {
      acc.bruto.push(d.bruto)
      acc.liquido.push(d.liquido)
      acc.fechamentos.push(d.fechamentos)
      acc.ticket.push(d.fechamentos > 0 ? d.bruto / d.fechamentos : 0)
      // Ancora ao meio-dia BRT pra fugir do drift de fuso na borda do dia.
      acc.rotulos.push(FMT_DIA_TOOLTIP.format(new Date(`${d.dia}T12:00:00-03:00`)))
      return acc
    },
    { bruto: [], liquido: [], fechamentos: [], ticket: [], rotulos: [] },
  )
}

export function PainelFinanceiro({
  resumo,
  serie,
  loading,
  onSelecionarModelo,
}: {
  resumo: FinanceiroResumoResponse | null
  serie: FinanceiroSerieResponse | null
  loading: boolean
  onSelecionarModelo?: (modeloId: string) => void
}) {
  const sparks = useMemo(
    () => derivarSparklines(serie?.serie_diaria ?? []),
    [serie?.serie_diaria],
  )

  if (loading && !resumo) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[124px] rounded-md" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Skeleton className="h-[148px] rounded-md sm:col-span-2" />
          <Skeleton className="h-[148px] rounded-md" />
        </div>
        <Skeleton className="h-[260px] w-full rounded-md" />
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <Skeleton className="h-[260px] rounded-md lg:col-span-2" />
          <Skeleton className="h-[260px] rounded-md" />
        </div>
      </div>
    )
  }
  if (!resumo) return null

  const r: FinanceiroResumo = resumo.resumo
  const ant = resumo.resumo_anterior
  const janela = resumo.janela_comparacao

  // Ticket médio = bruto / fechamentos. Útil contra outliers nos KPIs absolutos.
  const ticketMedio =
    r.fechamentos_total > 0 ? r.valor_bruto_brl / r.fechamentos_total : 0
  const ticketMedioAnterior =
    ant && ant.fechamentos_total > 0
      ? ant.valor_bruto_brl / ant.fechamentos_total
      : null

  return (
    <div className="space-y-4">
      {janela && (
        <div className="text-[11px] tabular-nums text-text-muted">
          deltas vs {janela.de} → {janela.ate}
        </div>
      )}

      {/* Primários: 3 KPIs above-the-fold com sparkline.
          Líquido em primeiro (hero gold) — é o resultado da Elite Baby. */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          rotulo="Líquido Elite Baby"
          valor={r.valor_liquido_brl}
          anterior={ant?.valor_liquido_brl ?? null}
          tom="brand"
          destaque
          hint="bruto − repasse calculado"
          sparkline={sparks.liquido}
          rotulosSparkline={sparks.rotulos}
        />
        <KpiCard
          rotulo="Faturamento bruto"
          valor={r.valor_bruto_brl}
          anterior={ant?.valor_bruto_brl ?? null}
          sparkline={sparks.bruto}
          rotulosSparkline={sparks.rotulos}
        />
        <KpiCard
          rotulo="Ticket médio"
          valor={ticketMedio}
          anterior={ticketMedioAnterior}
          hint={
            r.fechamentos_total > 0
              ? `${r.fechamentos_total} fechamento${r.fechamentos_total === 1 ? "" : "s"}`
              : "sem fechamentos no período"
          }
          sparkline={sparks.ticket}
          rotulosSparkline={sparks.rotulos}
        />
      </div>

      {/* Status (composto) + Fechamentos. O bloco composto conta a história
          quanto deve / quanto pagou / quanto falta, com progresso visual. */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <StatusRepasses
            calculado={r.valor_repasse_calculado_brl}
            pago={r.valor_repasse_pago_brl}
            saldo={r.valor_saldo_repasse_brl}
            bruto={r.valor_bruto_brl}
            semSnapshot={
              r.fechamentos_sem_snapshot > 0
                ? {
                    qtd: r.fechamentos_sem_snapshot,
                    valor: r.valor_sem_repasse_definido_brl,
                  }
                : undefined
            }
          />
        </div>
        <KpiCard
          rotulo="Fechamentos"
          valor={r.fechamentos_total}
          anterior={ant?.fechamentos_total ?? null}
          formato="int"
          sparkline={sparks.fechamentos}
          rotulosSparkline={sparks.rotulos}
        />
      </div>

      <ChartReceitaDiaria serie={serie?.serie_diaria ?? []} />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartTopModelos
            itens={serie?.top_modelos ?? []}
            onSelecionarModelo={onSelecionarModelo}
          />
        </div>
        <ChartMixForma itens={serie?.mix_forma_pagamento ?? []} />
      </div>
    </div>
  )
}
