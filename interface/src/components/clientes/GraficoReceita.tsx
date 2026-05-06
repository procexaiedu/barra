"use client"

import { formatBRL } from "@/lib/formatters"
import type { AtendimentoHistoricoItem } from "@/tipos/clientes"

function formatDataCurta(date: Date): string {
  const day = date.getDate().toString().padStart(2, "0")
  const months = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
  return `${day} ${months[date.getMonth()]}`
}

function formatBRLCurto(value: number): string {
  if (value >= 1000) {
    const k = value / 1000
    const frac = k % 1 === 0 ? "" : `,${Math.round((k % 1) * 10)}`
    return `R$ ${Math.floor(k)}${frac}k`
  }
  return `R$ ${Math.round(value).toLocaleString("pt-BR")}`
}

export function GraficoReceita({ historico }: { historico: AtendimentoHistoricoItem[] }) {
  const fechados = historico
    .filter((h): h is AtendimentoHistoricoItem & { valor_final: number } =>
      h.estado === "Fechado" && h.valor_final !== null
    )
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())

  if (fechados.length < 2) return null

  let cumsum = 0
  const pontos = fechados.map((h) => {
    cumsum += Number(h.valor_final)
    return { data: new Date(h.created_at), valor: cumsum, individual: Number(h.valor_final) }
  })

  const maxY = pontos[pontos.length - 1].valor
  if (maxY <= 0 || !isFinite(maxY)) return null

  const W = 600
  const H = 140
  const padTop = 24
  const padBottom = 28
  const padLeft = 62
  const padRight = 16
  const chartW = W - padLeft - padRight
  const chartH = H - padTop - padBottom

  const n = pontos.length

  const toX = (i: number) => padLeft + (n > 1 ? (i / (n - 1)) * chartW : chartW / 2)
  const toY = (valor: number) => padTop + chartH - (valor / maxY) * chartH

  const lineD = pontos.map((p, i) => `${i === 0 ? "M" : "L"} ${toX(i)} ${toY(p.valor)}`).join(" ")
  const areaD = `${lineD} L ${toX(n - 1)} ${padTop + chartH} L ${toX(0)} ${padTop + chartH} Z`

  const yTicks = [0.25, 0.5, 0.75, 1] as const

  return (
    <section aria-label="Gráfico de receita acumulada" className="rounded-lg border border-border bg-card p-5">
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        Receita acumulada
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ overflow: "visible" }}>
        {/* Grid lines */}
        {yTicks.map((t) => (
          <line
            key={t}
            x1={padLeft}
            x2={W - padRight}
            y1={padTop + chartH * (1 - t)}
            y2={padTop + chartH * (1 - t)}
            strokeWidth={0.5}
            strokeDasharray="4 4"
            style={{ stroke: "var(--color-border)" }}
          />
        ))}

        {/* Y labels */}
        {([0.5, 1] as const).map((t) => (
          <text
            key={t}
            x={padLeft - 8}
            y={padTop + chartH * (1 - t) + 4}
            textAnchor="end"
            fontSize={9}
            style={{ fill: "var(--color-text-muted)" }}
          >
            {formatBRLCurto(maxY * t)}
          </text>
        ))}

        {/* Area fill */}
        <path d={areaD} style={{ fill: "var(--color-state-closed)", opacity: 0.07 }} />

        {/* Line */}
        <path
          d={lineD}
          fill="none"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ stroke: "var(--color-state-closed)" }}
        />

        {/* Dots + X labels */}
        {pontos.map((p, i) => {
          const x = toX(i)
          const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle"
          return (
            <g key={i}>
              <circle cx={x} cy={toY(p.valor)} r={3} style={{ fill: "var(--color-state-closed)" }} />
              <text
                x={x}
                y={H - 4}
                textAnchor={anchor}
                fontSize={9}
                style={{ fill: "var(--color-text-muted)" }}
              >
                {formatDataCurta(p.data)}
              </text>
            </g>
          )
        })}

        {/* Final value annotation */}
        <text
          x={toX(n - 1)}
          y={toY(pontos[n - 1].valor) - 8}
          textAnchor="end"
          fontSize={10}
          fontWeight={600}
          style={{ fill: "var(--color-state-closed)" }}
        >
          {formatBRL(pontos[n - 1].valor)}
        </text>
      </svg>
    </section>
  )
}
