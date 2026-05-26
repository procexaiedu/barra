"use client"

import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroResumo, FinanceiroResumoResponse } from "@/tipos/financeiro"

interface CardKpiProps {
  rotulo: string
  valor: number
  anterior: number | null
  formato?: "brl" | "int"
  destaque?: "positivo" | "negativo" | null
  hint?: string
}

function CardKpi({ rotulo, valor, anterior, formato = "brl", destaque = null, hint }: CardKpiProps) {
  const formatado = formato === "brl" ? formatBRL(valor) : valor.toString()
  let deltaTxt: string | null = null
  let deltaCor = "text-text-muted"
  if (anterior !== null && anterior !== 0) {
    const delta = ((valor - anterior) / Math.abs(anterior)) * 100
    const sinal = delta >= 0 ? "+" : ""
    deltaTxt = `${sinal}${delta.toFixed(1)}% vs anterior`
    if (delta > 0) deltaCor = "text-success"
    else if (delta < 0) deltaCor = "text-destructive"
  }
  const valorCor =
    destaque === "negativo" && valor < 0
      ? "text-destructive"
      : destaque === "positivo"
      ? "text-success"
      : "text-text-primary"

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-text-muted">{rotulo}</div>
      <div className={`mt-1 text-2xl font-semibold ${valorCor}`}>{formatado}</div>
      {hint && <div className="mt-0.5 text-[11px] text-text-muted">{hint}</div>}
      {deltaTxt && <div className={`mt-2 text-xs ${deltaCor}`}>{deltaTxt}</div>}
    </div>
  )
}

export function PainelFinanceiro({
  resumo,
  loading,
}: {
  resumo: FinanceiroResumoResponse | null
  loading: boolean
}) {
  if (loading && !resumo) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    )
  }
  if (!resumo) return null

  const r: FinanceiroResumo = resumo.resumo
  const ant = resumo.resumo_anterior

  const hintComparacao = resumo.janela_comparacao
    ? `comparado a ${resumo.janela_comparacao.de} → ${resumo.janela_comparacao.ate}`
    : undefined

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <CardKpi
          rotulo="Faturamento bruto"
          valor={r.valor_bruto_brl}
          anterior={ant?.valor_bruto_brl ?? null}
          hint={hintComparacao}
        />
        <CardKpi
          rotulo="Repasses (calculado)"
          valor={r.valor_repasse_calculado_brl}
          anterior={ant?.valor_repasse_calculado_brl ?? null}
        />
        <CardKpi
          rotulo="Despesas"
          valor={r.valor_despesas_brl}
          anterior={ant?.valor_despesas_brl ?? null}
        />
        <CardKpi
          rotulo="Líquido da agência"
          valor={r.valor_liquido_brl}
          anterior={ant?.valor_liquido_brl ?? null}
          destaque="positivo"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <CardKpi
          rotulo="Repasses pagos"
          valor={r.valor_repasse_pago_brl}
          anterior={ant?.valor_repasse_pago_brl ?? null}
        />
        <CardKpi
          rotulo="Saldo a pagar"
          valor={r.valor_saldo_repasse_brl}
          anterior={ant?.valor_saldo_repasse_brl ?? null}
          destaque={r.valor_saldo_repasse_brl < 0 ? "negativo" : null}
          hint={
            r.valor_saldo_repasse_brl < 0
              ? "Pago a mais que o calculado (estorno?)"
              : undefined
          }
        />
        <CardKpi
          rotulo="Fechamentos"
          valor={r.fechamentos_total}
          anterior={ant?.fechamentos_total ?? null}
          formato="int"
          hint={
            r.fechamentos_sem_snapshot > 0
              ? `${r.fechamentos_sem_snapshot} sem repasse definido`
              : undefined
          }
        />
        <CardKpi
          rotulo="Sem repasse definido"
          valor={r.valor_sem_repasse_definido_brl}
          anterior={ant?.valor_sem_repasse_definido_brl ?? null}
          hint="Atendimentos fechados sem percentual"
        />
      </div>
    </div>
  )
}
