"use client"

import { Skeleton } from "@/components/ui/skeleton"
import type { FinanceiroResumo, FinanceiroResumoResponse } from "@/tipos/financeiro"
import { KpiCard } from "./KpiCard"

export function PainelFinanceiro({
  resumo,
  loading,
}: {
  resumo: FinanceiroResumoResponse | null
  loading: boolean
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

  const semRepasseLimpo = r.fechamentos_sem_snapshot === 0

  return (
    <div className="space-y-3">
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
          rotulo="Sem repasse definido"
          valor={r.valor_sem_repasse_definido_brl}
          anterior={ant?.valor_sem_repasse_definido_brl ?? null}
          tom={semRepasseLimpo ? "muted" : "warning"}
          sentido="maior_pior"
          okQuando={semRepasseLimpo}
          okTexto="todos com % definido"
          hint={
            semRepasseLimpo
              ? "atendimentos sem percentual aparecem aqui"
              : `${r.fechamentos_sem_snapshot} atendimento${r.fechamentos_sem_snapshot > 1 ? "s" : ""} para revisar`
          }
        />
      </div>
    </div>
  )
}
