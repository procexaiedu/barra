"use client"

import { Skeleton } from "@/components/ui/skeleton"
import type {
  FinanceiroResumo,
  FinanceiroResumoResponse,
  FinanceiroSerieResponse,
} from "@/tipos/financeiro"
import { KpiCard } from "./KpiCard"
import { ChartReceitaDiaria } from "./charts/ChartReceitaDiaria"
import { ChartTopModelos } from "./charts/ChartTopModelos"
import { ChartMixForma } from "./charts/ChartMixForma"

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
  if (loading && !resumo) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[112px] rounded-md" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[112px] rounded-md" />
          ))}
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

  const pctRepasseDoBruto =
    r.valor_bruto_brl > 0
      ? `${((r.valor_repasse_calculado_brl / r.valor_bruto_brl) * 100).toFixed(1)}% do bruto`
      : undefined

  const pctPagoDoCalculado =
    r.valor_repasse_calculado_brl > 0
      ? (r.valor_repasse_pago_brl / r.valor_repasse_calculado_brl) * 100
      : 0

  const saldoZero = r.valor_saldo_repasse_brl === 0
  const saldoNegativo = r.valor_saldo_repasse_brl < 0
  const tomSaldo = saldoNegativo
    ? "danger"
    : saldoZero
      ? "success"
      : "warning"

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

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          rotulo="Faturamento bruto"
          valor={r.valor_bruto_brl}
          anterior={ant?.valor_bruto_brl ?? null}
        />
        <KpiCard
          rotulo="Repasses (calculado)"
          valor={r.valor_repasse_calculado_brl}
          anterior={ant?.valor_repasse_calculado_brl ?? null}
          sentido="neutro"
          hint={pctRepasseDoBruto}
        />
        <KpiCard
          rotulo="Líquido da agência"
          valor={r.valor_liquido_brl}
          anterior={ant?.valor_liquido_brl ?? null}
          tom="brand"
          destaque
          hint="= bruto − repasse"
        />
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          rotulo="Repasses pagos"
          valor={r.valor_repasse_pago_brl}
          anterior={ant?.valor_repasse_pago_brl ?? null}
          sentido="neutro"
          progresso={pctPagoDoCalculado}
          trailing={
            r.valor_repasse_calculado_brl > 0
              ? `${pctPagoDoCalculado.toFixed(0)}%`
              : undefined
          }
        />
        <KpiCard
          rotulo="Saldo a pagar"
          valor={r.valor_saldo_repasse_brl}
          anterior={ant?.valor_saldo_repasse_brl ?? null}
          tom={tomSaldo}
          sentido="maior_pior"
          hint={
            saldoNegativo
              ? "pago a mais (estorno?)"
              : saldoZero
                ? "tudo em dia"
                : "= calculado − pagos"
          }
        />
        <KpiCard
          rotulo="Fechamentos"
          valor={r.fechamentos_total}
          anterior={ant?.fechamentos_total ?? null}
          formato="int"
          hint={
            r.fechamentos_sem_snapshot > 0
              ? `${r.fechamentos_sem_snapshot} sem % definido`
              : undefined
          }
        />
        <KpiCard
          rotulo="Ticket médio"
          valor={ticketMedio}
          anterior={ticketMedioAnterior}
          hint={
            r.fechamentos_total > 0
              ? `= bruto / ${r.fechamentos_total} fechamento${r.fechamentos_total === 1 ? "" : "s"}`
              : "sem fechamentos no período"
          }
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

      {r.fechamentos_sem_snapshot > 0 && (
        <div className="rounded-md border border-warn-500/30 bg-warn-500/[0.04] px-3 py-2 text-[12px] text-warn-500">
          <span className="font-medium">{r.fechamentos_sem_snapshot}</span>{" "}
          atendimento{r.fechamentos_sem_snapshot === 1 ? "" : "s"} sem % de
          repasse definido (
          <span className="tabular-nums">
            {new Intl.NumberFormat("pt-BR", {
              style: "currency",
              currency: "BRL",
            }).format(r.valor_sem_repasse_definido_brl)}
          </span>
          ). Acesse a aba Repasses para preencher retroativamente.
        </div>
      )}

    </div>
  )
}
