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
import type { SaldoModelo } from "@/tipos/financeiro"
import { ChartShell, LegendaItem } from "./ChartReceitaDiaria"

interface Props {
  items: SaldoModelo[]
  onSelecionarModelo?: (modeloId: string) => void
}

interface Linha {
  modelo_id: string
  modelo_nome: string
  saldo: number
  saldoAbs: number
  pctDoTotal: number
  fechamentos: number
  negativo: boolean
}

const FMT_BRL_CURTO = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
  style: "currency",
  currency: "BRL",
})

const TOP_N = 8

// Distribuição do saldo a pagar entre as modelos. Ordena por |saldo| descendente
// para que o "Pareto" da dívida fique óbvio — quem concentra mais ficha no topo.
// Saldo negativo (estorno) entra em vermelho com mesma ordenação por magnitude.
// Modelos com saldo zero ficam fora; um rodapé mostra quantas estão em dia.
export function ChartDistribuicaoSaldo({ items, onSelecionarModelo }: Props) {
  const { linhas, escondidas, totalSaldo, emDia } = useMemo(() => {
    const naoZeradas = items.filter((s) => Math.abs(s.saldo) >= 0.005)
    const ordenadas = [...naoZeradas].sort(
      (a, b) => Math.abs(b.saldo) - Math.abs(a.saldo),
    )
    const totalSaldo = ordenadas.reduce((acc, s) => acc + s.saldo, 0)
    const totalAbs = ordenadas.reduce((acc, s) => acc + Math.abs(s.saldo), 0)
    const visiveis = ordenadas.slice(0, TOP_N)
    const restoQtd = ordenadas.length - visiveis.length

    const linhas: Linha[] = visiveis.map((s) => ({
      modelo_id: s.modelo_id,
      modelo_nome: s.modelo_nome,
      saldo: s.saldo,
      saldoAbs: Math.abs(s.saldo),
      pctDoTotal: totalAbs > 0 ? (Math.abs(s.saldo) / totalAbs) * 100 : 0,
      fechamentos: s.fechamentos_total,
      negativo: s.saldo < 0,
    }))

    return {
      linhas,
      escondidas: restoQtd,
      totalSaldo,
      emDia: items.length - naoZeradas.length,
    }
  }, [items])

  if (linhas.length === 0) {
    return (
      <ChartShell
        titulo="Distribuição do saldo"
        hint={emDia > 0 ? `${emDia} ${emDia === 1 ? "modelo" : "modelos"} em dia` : undefined}
      >
        <div className="flex h-[180px] items-center justify-center text-sm text-text-muted">
          Nenhum saldo pendente neste período.
        </div>
      </ChartShell>
    )
  }

  // Altura ~32px por barra + margens; mínimo 200px.
  const altura = Math.max(200, linhas.length * 32 + 24)
  const temNegativos = linhas.some((l) => l.negativo)

  const hintBase = `${linhas.length}${escondidas > 0 ? `+${escondidas}` : ""} ${
    linhas.length + escondidas === 1 ? "modelo" : "modelos"
  } com saldo · total ${formatBRL(totalSaldo)}`

  return (
    <ChartShell
      titulo="Distribuição do saldo por modelo"
      hint={hintBase}
      legenda={
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <LegendaItem cor="var(--warn-500)" rotulo="A pagar" />
          {temNegativos && <LegendaItem cor="var(--danger-500)" rotulo="Pago a mais" />}
        </div>
      }
    >
      <div style={{ height: altura }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={linhas}
            layout="vertical"
            margin={{ top: 4, right: 72, bottom: 4, left: 0 }}
            barCategoryGap={4}
          >
            <XAxis type="number" hide domain={[0, "dataMax"]} />
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
              content={<TooltipSaldo />}
            />
            <Bar
              dataKey="saldoAbs"
              name="Saldo"
              isAnimationActive={false}
              radius={[0, 2, 2, 0]}
              onClick={(d: { payload?: Linha }) => {
                if (onSelecionarModelo && d?.payload?.modelo_id) {
                  onSelecionarModelo(d.payload.modelo_id)
                }
              }}
              style={{ cursor: onSelecionarModelo ? "pointer" : undefined }}
            >
              {linhas.map((l) => (
                <Cell
                  key={l.modelo_id}
                  fill={l.negativo ? "var(--danger-500)" : "var(--warn-500)"}
                  fillOpacity={l.negativo ? 0.85 : 0.92}
                />
              ))}
              <LabelList
                dataKey="saldoAbs"
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

      {(escondidas > 0 || emDia > 0) && (
        <p className="-mt-1 text-[11px] text-text-disabled">
          {escondidas > 0 && (
            <>
              +{escondidas} {escondidas === 1 ? "modelo" : "modelos"} fora do top {TOP_N}
            </>
          )}
          {escondidas > 0 && emDia > 0 && <span className="mx-1.5">·</span>}
          {emDia > 0 && (
            <>
              {emDia} {emDia === 1 ? "modelo" : "modelos"} em dia
            </>
          )}
        </p>
      )}
    </ChartShell>
  )
}

function TooltipSaldo({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: Linha }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const cor = p.negativo ? "var(--danger-500)" : "var(--warn-500)"
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
      <div className="mb-1 font-medium text-text-primary">{p.modelo_nome}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 tabular-nums">
        <dt style={{ color: cor }}>{p.negativo ? "Pago a mais" : "Saldo"}</dt>
        <dd className="text-right" style={{ color: cor }}>
          {p.negativo ? "−" : ""}
          {formatBRL(p.saldoAbs)}{" "}
          <span className="text-[10px] text-text-muted">({p.pctDoTotal.toFixed(1)}%)</span>
        </dd>
        <dt className="text-text-muted">Fechamentos</dt>
        <dd className="text-right text-text-secondary">{p.fechamentos}</dd>
      </dl>
    </div>
  )
}
