"use client"

import { useMemo } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts"
import { formatBRL } from "@/lib/formatters"
import type { RepassePagoResponse } from "@/tipos/financeiro"
import { ChartShell } from "./ChartReceitaDiaria"

interface Props {
  pagamentos: RepassePagoResponse[]
  // YYYY-MM-DD; quando ausente, deriva apenas dos pagamentos existentes.
  janelaDe?: string | null
  janelaAte?: string | null
}

interface Ponto {
  dia: string
  diaIso: string
  diaCurto: string
  valor: number
  qtd: number
  modelosDistintas: number
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

// Agrupa pagamentos por dia (BRT). Quando a janela [de, ate] vem do filtro,
// preenche dias sem pagamento com zero para não distorcer o eixo X — assim a
// mesma forma de cadência (~ChartReceitaDiaria) lê com a mesma intuição.
export function ChartRitmoPagamento({ pagamentos, janelaDe, janelaAte }: Props) {
  const pontos = useMemo<Ponto[]>(() => {
    if (pagamentos.length === 0 && (!janelaDe || !janelaAte)) return []

    const buckets = new Map<
      string,
      { valor: number; qtd: number; modelos: Set<string> }
    >()

    for (const p of pagamentos) {
      // data_pagamento já vem como YYYY-MM-DD (date, não timestamp).
      const dia = p.data_pagamento.slice(0, 10)
      const slot = buckets.get(dia) ?? {
        valor: 0,
        qtd: 0,
        modelos: new Set<string>(),
      }
      slot.valor += p.valor
      slot.qtd += 1
      slot.modelos.add(p.modelo_id)
      buckets.set(dia, slot)
    }

    // Decide quais dias renderizar:
    // - Se temos janela: enumera todos os dias da janela (preenchendo zeros).
    //   Cap a 92 dias pra evitar barras-cabelo em "Tudo".
    // - Se não temos janela mas há pagamentos: usa só os dias com lançamento.
    let dias: string[] = []
    if (janelaDe && janelaAte) {
      const span = diasEntre(janelaDe, janelaAte)
      if (span <= 92) {
        dias = enumerarDias(janelaDe, janelaAte)
      } else {
        dias = Array.from(buckets.keys()).sort()
      }
    } else {
      dias = Array.from(buckets.keys()).sort()
    }

    return dias.map<Ponto>((diaIso) => {
      const slot = buckets.get(diaIso)
      const dt = new Date(`${diaIso}T12:00:00-03:00`)
      return {
        dia: FMT_DIA_LONGO.format(dt),
        diaIso,
        diaCurto: FMT_DIA_CURTO.format(dt),
        valor: slot?.valor ?? 0,
        qtd: slot?.qtd ?? 0,
        modelosDistintas: slot?.modelos.size ?? 0,
      }
    })
  }, [pagamentos, janelaDe, janelaAte])

  const totalPago = useMemo(
    () => pagamentos.reduce((acc, p) => acc + p.valor, 0),
    [pagamentos],
  )
  const diasComPagamento = pontos.filter((p) => p.valor > 0).length

  if (pagamentos.length === 0) {
    return (
      <ChartShell titulo="Ritmo de pagamento">
        <div className="flex h-[220px] flex-col items-center justify-center gap-1 text-sm text-text-muted">
          <span>Nenhum pagamento registrado neste período.</span>
          <span className="text-[11px] text-text-disabled">
            Os pagamentos aparecem aqui assim que forem lançados.
          </span>
        </div>
      </ChartShell>
    )
  }

  const intervaloX =
    pontos.length <= 14 ? 0 : pontos.length <= 31 ? 2 : Math.ceil(pontos.length / 12)

  const hint = `${diasComPagamento} ${
    diasComPagamento === 1 ? "dia com pagamento" : "dias com pagamento"
  } · ${formatBRL(totalPago)} no total`

  return (
    <ChartShell titulo="Ritmo de pagamento" hint={hint}>
      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
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
              tickFormatter={(v: number) => FMT_BRL_CURTO.format(v)}
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={64}
            />
            <RechartsTooltip
              cursor={{ fill: "var(--ink-200)", fillOpacity: 0.4 }}
              wrapperStyle={{ outline: "none" }}
              content={<TooltipRitmo />}
            />
            <Bar
              dataKey="valor"
              name="Pago"
              fill="var(--success-500)"
              fillOpacity={0.9}
              isAnimationActive={false}
              radius={[2, 2, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartShell>
  )
}

function TooltipRitmo({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: Ponto }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  if (p.valor === 0) {
    return (
      <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
        <div className="font-medium text-text-primary">{p.dia}</div>
        <div className="text-text-muted">Sem pagamentos</div>
      </div>
    )
  }
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-[12px] shadow-lg shadow-black/40">
      <div className="mb-1 font-medium text-text-primary">{p.dia}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 tabular-nums">
        <dt style={{ color: "var(--success-500)" }}>Pago</dt>
        <dd className="text-right" style={{ color: "var(--success-500)" }}>
          {formatBRL(p.valor)}
        </dd>
        <dt className="text-text-muted">Lançamentos</dt>
        <dd className="text-right text-text-secondary">{p.qtd}</dd>
        {p.modelosDistintas > 1 && (
          <>
            <dt className="text-text-muted">Modelos</dt>
            <dd className="text-right text-text-secondary">{p.modelosDistintas}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

function diasEntre(deIso: string, ateIso: string): number {
  const a = new Date(`${deIso}T00:00:00-03:00`).getTime()
  const b = new Date(`${ateIso}T00:00:00-03:00`).getTime()
  return Math.round((b - a) / 86_400_000) + 1
}

function enumerarDias(deIso: string, ateIso: string): string[] {
  const out: string[] = []
  const cur = new Date(`${deIso}T00:00:00-03:00`)
  const ate = new Date(`${ateIso}T00:00:00-03:00`)
  while (cur.getTime() <= ate.getTime()) {
    out.push(cur.toISOString().slice(0, 10))
    cur.setUTCDate(cur.getUTCDate() + 1)
  }
  return out
}
