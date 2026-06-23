"use client"

import { useMemo } from "react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroSerieDia } from "@/tipos/financeiro"

interface Props {
  serie: FinanceiroSerieDia[]
}

interface Ponto {
  dia: string
  diaIso: string
  diaCurto: string
  liquido: number
  repasse: number
  bruto: number
  fechamentos: number
  acumulado: number
}

const FMT_DIA_CURTO = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  timeZone: "America/Sao_Paulo",
})
const FMT_DIA_LONGO = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "long",
  year: "numeric",
  weekday: "short",
  timeZone: "America/Sao_Paulo",
})
const FMT_BRL_CURTO = new Intl.NumberFormat("pt-BR", {
  notation: "compact",
  maximumFractionDigits: 1,
  style: "currency",
  currency: "BRL",
})

export function ChartReceitaDiaria({ serie }: Props) {
  const pontos = useMemo<Ponto[]>(() => {
    return serie.reduce<Ponto[]>((acc, s) => {
      const acumuladoAnterior = acc.length > 0 ? acc[acc.length - 1].acumulado : 0
      const dt = new Date(`${s.dia}T12:00:00-03:00`)
      acc.push({
        dia: FMT_DIA_LONGO.format(dt),
        diaIso: s.dia,
        diaCurto: FMT_DIA_CURTO.format(dt),
        liquido: s.liquido,
        repasse: s.repasse_calculado,
        bruto: s.bruto,
        fechamentos: s.fechamentos,
        acumulado: acumuladoAnterior + s.bruto,
      })
      return acc
    }, [])
  }, [serie])

  const totalBruto = pontos.length ? pontos[pontos.length - 1].acumulado : 0
  const diasComReceita = pontos.filter((p) => p.bruto > 0).length

  // Intervalo do eixo X: mais denso conforme cresce o período.
  const intervaloX =
    pontos.length <= 14 ? 0 : pontos.length <= 31 ? 2 : Math.ceil(pontos.length / 12)

  if (pontos.length === 0 || totalBruto === 0) {
    return (
      <ChartShell titulo="Receita diária" hint={`${pontos.length} dia${pontos.length === 1 ? "" : "s"} no período`}>
        <div className="flex h-[220px] items-center justify-center text-sm text-text-muted">
          Sem fechamentos no período.
        </div>
      </ChartShell>
    )
  }

  return (
    <ChartShell
      titulo="Receita diária"
      hint={`${diasComReceita} de ${pontos.length} dia${pontos.length === 1 ? "" : "s"} com fechamento`}
      legenda={
        <div className="flex items-center gap-3 text-[11px] text-text-secondary">
          <LegendaItem cor="var(--gold-500)" rotulo="Líquido" />
          <LegendaItem cor="var(--chart-2)" rotulo="Repasse" />
          <LegendaItem cor="var(--text-secondary)" rotulo="Bruto acum." linha />
        </div>
      }
    >
      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={pontos}
            margin={{ top: 8, right: 12, bottom: 4, left: 0 }}
            barCategoryGap={pontos.length > 31 ? "10%" : "20%"}
          >
            <CartesianGrid
              stroke="var(--ink-300)"
              strokeOpacity={0.5}
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="diaCurto"
              interval={intervaloX}
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "var(--ink-400)" }}
              minTickGap={8}
            />
            <YAxis
              yAxisId="bar"
              tickFormatter={(v: number) => FMT_BRL_CURTO.format(v)}
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={64}
            />
            <YAxis
              yAxisId="acc"
              orientation="right"
              tickFormatter={(v: number) => FMT_BRL_CURTO.format(v)}
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={64}
            />
            <RechartsTooltip
              cursor={{ fill: "var(--ink-200)", fillOpacity: 0.4 }}
              wrapperStyle={{ outline: "none" }}
              content={<TooltipReceitaDiaria />}
            />
            <Bar
              yAxisId="bar"
              dataKey="liquido"
              stackId="receita"
              name="Líquido"
              fill="var(--gold-500)"
              isAnimationActive={false}
              radius={[0, 0, 0, 0]}
            />
            <Bar
              yAxisId="bar"
              dataKey="repasse"
              stackId="receita"
              name="Repasse"
              fill="var(--chart-2)"
              isAnimationActive={false}
              radius={[2, 2, 0, 0]}
            />
            <Line
              yAxisId="acc"
              type="monotone"
              dataKey="acumulado"
              name="Bruto acumulado"
              stroke="var(--text-secondary)"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </ChartShell>
  )
}

function TooltipReceitaDiaria({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: Ponto }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
      <div className="mb-1 font-medium text-text-primary">{p.dia}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        <dt className="text-text-muted">Bruto</dt>
        <dd className="text-right font-mono tabular-nums text-text-primary">{formatBRL(p.bruto)}</dd>
        <dt className="text-gold-700">Líquido</dt>
        <dd className="text-right font-mono tabular-nums text-gold-700">{formatBRL(p.liquido)}</dd>
        <dt style={{ color: "var(--chart-2)" }}>Repasse</dt>
        <dd className="text-right font-mono tabular-nums" style={{ color: "var(--chart-2)" }}>
          {formatBRL(p.repasse)}
        </dd>
        <dt className="text-text-muted">Fechamentos</dt>
        <dd className="text-right font-mono tabular-nums text-text-secondary">{p.fechamentos}</dd>
        <dt className="border-t border-border/60 pt-1 text-text-muted">Acumulado</dt>
        <dd className="border-t border-border/60 pt-1 text-right font-mono tabular-nums text-text-secondary">
          {formatBRL(p.acumulado)}
        </dd>
      </dl>
    </div>
  )
}

// ---------- Sub-componentes compartilhados ----------

export function ChartShell({
  titulo,
  hint,
  legenda,
  children,
}: {
  titulo: string
  hint?: React.ReactNode
  legenda?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-border-subtle shadow-elev-1">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-3">
          <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-primary">
            <span className="h-3 w-0.5 rounded-full bg-gold-500" aria-hidden />
            {titulo}
          </h3>
          {hint && <span className="text-[11px] text-text-disabled">{hint}</span>}
        </div>
        {legenda}
      </header>
      {children}
    </section>
  )
}

export function LegendaItem({
  cor,
  rotulo,
  linha,
}: {
  cor: string
  rotulo: string
  linha?: boolean
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {linha ? (
        <span
          aria-hidden
          className="inline-block h-0 w-3.5"
          style={{ borderTop: `1.5px dashed ${cor}` }}
        />
      ) : (
        <span
          aria-hidden
          className="inline-block size-2 rounded-sm"
          style={{ background: cor }}
        />
      )}
      {rotulo}
    </span>
  )
}
