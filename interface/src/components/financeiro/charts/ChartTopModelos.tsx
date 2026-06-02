"use client"

import { useMemo } from "react"
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroTopModelo } from "@/tipos/financeiro"
import { ChartShell, LegendaItem } from "./ChartReceitaDiaria"

interface Props {
  itens: FinanceiroTopModelo[]
  onSelecionarModelo?: (modeloId: string) => void
}

interface Linha {
  modelo_id: string
  modelo_nome: string
  liquido: number
  repasse: number
  bruto: number
  fechamentos: number
  pctDoTotal: number
}

const FMT_BRL_CURTO = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
  style: "currency",
  currency: "BRL",
})

export function ChartTopModelos({ itens, onSelecionarModelo }: Props) {
  const linhas = useMemo<Linha[]>(() => {
    const total = itens.reduce((acc, m) => acc + m.bruto, 0)
    return itens.map((m) => ({
      modelo_id: m.modelo_id,
      modelo_nome: m.modelo_nome,
      liquido: m.liquido,
      repasse: m.repasse_calculado,
      bruto: m.bruto,
      fechamentos: m.fechamentos,
      pctDoTotal: total > 0 ? (m.bruto / total) * 100 : 0,
    }))
  }, [itens])

  if (linhas.length === 0) {
    return (
      <ChartShell titulo="Top modelos no período">
        <div className="flex h-[220px] items-center justify-center text-sm text-text-muted">
          Sem fechamentos no período.
        </div>
      </ChartShell>
    )
  }

  // Altura proporcional ao número de barras. Mínimo 200, ideal ~32px por linha + margens.
  const altura = Math.max(200, linhas.length * 36 + 32)

  return (
    <ChartShell
      titulo="Top modelos no período"
      hint={`${linhas.length} ${linhas.length === 1 ? "modelo" : "modelos"} · ordenado por bruto`}
      legenda={
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <LegendaItem cor="var(--gold-500)" rotulo="Líquido" />
          <LegendaItem cor="var(--chart-2)" rotulo="Repasse" />
        </div>
      }
    >
      <div style={{ height: altura }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={linhas}
            layout="vertical"
            margin={{ top: 0, right: 64, bottom: 0, left: 0 }}
            barCategoryGap={6}
          >
            <XAxis
              type="number"
              hide
              domain={[0, "dataMax"]}
            />
            <YAxis
              type="category"
              dataKey="modelo_nome"
              tick={{ fill: "var(--text-secondary)", fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={120}
              interval={0}
            />
            <RechartsTooltip
              cursor={{ fill: "var(--ink-200)", fillOpacity: 0.4 }}
              wrapperStyle={{ outline: "none" }}
              content={<TooltipTopModelo />}
            />
            <Bar
              dataKey="liquido"
              stackId="bruto"
              name="Líquido"
              fill="var(--gold-500)"
              isAnimationActive={false}
              onClick={(d: { payload?: Linha }) => {
                if (onSelecionarModelo && d?.payload?.modelo_id) {
                  onSelecionarModelo(d.payload.modelo_id)
                }
              }}
              style={{ cursor: onSelecionarModelo ? "pointer" : undefined }}
            >
              {linhas.map((l, i) => (
                <Cell key={l.modelo_id} fillOpacity={escala(i, linhas.length)} />
              ))}
            </Bar>
            <Bar
              dataKey="repasse"
              stackId="bruto"
              name="Repasse"
              fill="var(--chart-2)"
              isAnimationActive={false}
              radius={[0, 2, 2, 0]}
              onClick={(d: { payload?: Linha }) => {
                if (onSelecionarModelo && d?.payload?.modelo_id) {
                  onSelecionarModelo(d.payload.modelo_id)
                }
              }}
              style={{ cursor: onSelecionarModelo ? "pointer" : undefined }}
            >
              <LabelList
                dataKey="bruto"
                position="right"
                offset={6}
                fill="var(--text-secondary)"
                fontSize={11}
                formatter={(value: unknown) =>
                  typeof value === "number" ? FMT_BRL_CURTO.format(value) : ""
                }
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartShell>
  )
}

// A modelo #1 fica em gold-500 cheio; demais decrescem em opacidade até 0.55.
// Mantém a hierarquia visual sem trocar a categoria cromática.
function escala(idx: number, total: number): number {
  if (total <= 1) return 1
  const min = 0.55
  const max = 1
  const t = idx / (total - 1)
  return max - (max - min) * t
}

function TooltipTopModelo({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: Linha }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
      <div className="mb-1 font-medium text-text-primary">{p.modelo_nome}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        <dt className="text-text-muted">Bruto</dt>
        <dd className="text-right font-mono tabular-nums text-text-primary">
          {formatBRL(p.bruto)}{" "}
          <span className="text-[10px] text-text-muted">({p.pctDoTotal.toFixed(1)}%)</span>
        </dd>
        <dt className="text-gold-700">Líquido</dt>
        <dd className="text-right font-mono tabular-nums text-gold-700">{formatBRL(p.liquido)}</dd>
        <dt style={{ color: "var(--chart-2)" }}>Repasse</dt>
        <dd className="text-right font-mono tabular-nums" style={{ color: "var(--chart-2)" }}>
          {formatBRL(p.repasse)}
        </dd>
        <dt className="text-text-muted">Fechamentos</dt>
        <dd className="text-right font-mono tabular-nums text-text-secondary">{p.fechamentos}</dd>
      </dl>
    </div>
  )
}
