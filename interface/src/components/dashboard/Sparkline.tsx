"use client"

import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip as RechartsTooltip } from "recharts"
import type { SerieTemporalPonto } from "@/tipos/dashboard"

interface Props {
  pontos: SerieTemporalPonto[]
  cor?: string
  altura?: number
  ariaLabel?: string
  formatarValor?: (valor: number) => string
}

export function Sparkline({
  pontos,
  cor = "var(--gold-500)",
  altura = 36,
  ariaLabel,
  formatarValor,
}: Props) {
  if (!pontos || pontos.length === 0) {
    return <div aria-hidden style={{ height: altura }} />
  }

  const dadosNumericos = pontos.map((p) => ({
    data: p.data,
    valor: p.valor ?? 0,
    bruto: p.valor,
  }))

  return (
    <div aria-label={ariaLabel} role="img" style={{ height: altura, width: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={dadosNumericos} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <YAxis hide domain={["auto", "auto"]} />
          <RechartsTooltip
            cursor={{ stroke: "var(--text-muted)", strokeOpacity: 0.25 }}
            wrapperStyle={{ outline: "none" }}
            contentStyle={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: "4px 8px",
              fontSize: 12,
            }}
            labelFormatter={() => ""}
            formatter={(_valor: unknown, _nome: unknown, item: { payload?: { data: string; bruto: number | null } }) => {
              const ponto = item?.payload
              if (!ponto) return ["", ""]
              const dataLegivel = new Date(`${ponto.data}T12:00:00-03:00`).toLocaleDateString("pt-BR", {
                day: "2-digit",
                month: "short",
              })
              const valorFmt =
                ponto.bruto !== null
                  ? formatarValor
                    ? formatarValor(ponto.bruto)
                    : String(ponto.bruto)
                  : "—"
              return [valorFmt, dataLegivel]
            }}
          />
          <Line
            type="monotone"
            dataKey="valor"
            stroke={cor}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
