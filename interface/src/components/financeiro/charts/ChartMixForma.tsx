"use client"

import { useMemo } from "react"
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from "recharts"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroMixForma } from "@/tipos/financeiro"
import { ChartShell } from "./ChartReceitaDiaria"

interface Props {
  itens: FinanceiroMixForma[]
}

interface Fatia {
  forma: string
  rotulo: string
  valor: number
  fechamentos: number
  pct: number
  cor: string
}

// Ordem canônica do enum + 'indefinido'. Cor fixa por forma — não permutar para
// que a mesma forma de pagamento mantenha o mesmo tom entre períodos/telas.
const ORDEM: Array<{ id: string; rotulo: string; cor: string }> = [
  { id: "pix", rotulo: "Pix", cor: "var(--chart-1)" },
  { id: "dinheiro", rotulo: "Dinheiro", cor: "var(--chart-3)" },
  { id: "cartao", rotulo: "Cartão", cor: "var(--chart-2)" },
  { id: "outro", rotulo: "Outro", cor: "var(--chart-4)" },
  { id: "indefinido", rotulo: "Indefinido", cor: "var(--text-muted)" },
]

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function ChartMixForma({ itens }: Props) {
  const { fatias, total } = useMemo(() => {
    const total = itens.reduce((acc, x) => acc + x.valor_bruto, 0)
    const mapa = new Map(itens.map((x) => [x.forma_pagamento, x]))
    const fatias = ORDEM.map((o) => {
      const f = mapa.get(o.id)
      const valor = f?.valor_bruto ?? 0
      return {
        forma: o.id,
        rotulo: o.rotulo,
        valor,
        fechamentos: f?.fechamentos ?? 0,
        pct: total > 0 ? (valor / total) * 100 : 0,
        cor: o.cor,
      }
    })
    return { fatias, total }
  }, [itens])

  const fatiasVisiveis = fatias.filter((f) => f.valor > 0)

  if (total === 0) {
    return (
      <ChartShell titulo="Mix forma de pagamento">
        <div className="flex h-[220px] items-center justify-center text-sm text-text-muted">
          Sem fechamentos no período.
        </div>
      </ChartShell>
    )
  }

  return (
    <ChartShell
      titulo="Mix forma de pagamento"
      hint={`${fatiasVisiveis.length} formas registradas`}
    >
      <div className="grid grid-cols-[140px_1fr] items-center gap-3">
        <div className="relative h-[140px] w-[140px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={fatiasVisiveis}
                dataKey="valor"
                nameKey="rotulo"
                innerRadius="62%"
                outerRadius="100%"
                paddingAngle={fatiasVisiveis.length > 1 ? 2 : 0}
                stroke="var(--card)"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {fatiasVisiveis.map((f) => (
                  <Cell key={f.forma} fill={f.cor} style={{ outline: "none" }} />
                ))}
              </Pie>
              <RechartsTooltip
                wrapperStyle={{ outline: "none" }}
                content={<TooltipMix />}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-[10px] uppercase tracking-[0.14em] text-text-muted">
              Bruto
            </span>
            <span className="text-[13px] font-semibold tabular-nums text-text-primary">
              {formatBRL(total)}
            </span>
          </div>
        </div>

        <ul className="flex flex-col gap-1">
          {fatias.map((f) => {
            const inativo = f.valor === 0
            return (
              <li
                key={f.forma}
                className="grid grid-cols-[10px_1fr_auto] items-baseline gap-2"
              >
                <span
                  aria-hidden
                  className="inline-block size-2 rounded-sm"
                  style={{ background: f.cor, opacity: inativo ? 0.3 : 1 }}
                />
                <span
                  className={
                    inativo
                      ? "truncate text-[12px] text-text-muted"
                      : "truncate text-[12px] text-text-primary"
                  }
                >
                  {f.rotulo}
                </span>
                <span
                  className={
                    inativo
                      ? "text-[11px] tabular-nums text-text-disabled"
                      : "text-[11px] tabular-nums text-text-secondary"
                  }
                >
                  {PCT_FMT.format(f.pct)}%
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </ChartShell>
  )
}

function TooltipMix({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: Fatia }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
      <div className="mb-1 font-medium text-text-primary">{p.rotulo}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 tabular-nums">
        <dt className="text-text-muted">Bruto</dt>
        <dd className="text-right text-text-primary">{formatBRL(p.valor)}</dd>
        <dt className="text-text-muted">Fechamentos</dt>
        <dd className="text-right text-text-secondary">{p.fechamentos}</dd>
        <dt className="text-text-muted">% do mix</dt>
        <dd className="text-right text-text-secondary">{PCT_FMT.format(p.pct)}%</dd>
      </dl>
    </div>
  )
}
