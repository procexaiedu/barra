"use client"

import type { MotivoPerda } from "@/tipos/atendimentos"
import type { PerdaPorMotivoLinha } from "@/tipos/dashboard"

const ORDEM: MotivoPerda[] = [
  "sumiu",
  "preco",
  "risco",
  "indisponibilidade",
  "fora_de_area",
  "outro",
]

const OPACIDADE_POR_INDICE = [1, 0.85, 0.72, 0.6, 0.5, 0.42] as const

interface Fatia {
  motivo: MotivoPerda
  contagem: number
  dash: number
  gap: number
  offset: number
  opacidade: number
}

function calcularFatias(visiveis: PerdaPorMotivoLinha[], total: number, c: number): Fatia[] {
  let acumulado = 0
  return visiveis.map((linha, i) => {
    const pct = linha.contagem / total
    const dash = pct * c
    const gap = c - dash
    const offset = -acumulado * c
    acumulado += pct
    return {
      motivo: linha.motivo,
      contagem: linha.contagem,
      dash,
      gap,
      offset,
      opacidade: OPACIDADE_POR_INDICE[i] ?? 0.2,
    }
  })
}

interface Props {
  linhas: PerdaPorMotivoLinha[]
  total: number
}

export function DonutPerdas({ linhas, total }: Props) {
  if (total === 0) return null

  const visiveis = ORDEM.map((motivo) => linhas.find((l) => l.motivo === motivo)).filter(
    (l): l is PerdaPorMotivoLinha => Boolean(l && l.contagem > 0)
  )

  if (visiveis.length === 0) return null

  const cx = 50
  const cy = 50
  const r = 36
  const stroke = 14
  const c = 2 * Math.PI * r
  const fatias = calcularFatias(visiveis, total, c)

  return (
    <svg
      viewBox="0 0 100 100"
      role="img"
      aria-label={`Distribuição de ${total} perdas por motivo`}
      className="h-32 w-32 shrink-0"
    >
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="transparent"
        stroke="var(--ink-300)"
        strokeWidth={stroke}
      />
      <g transform={`rotate(-90 ${cx} ${cy})`}>
        {fatias.map((fatia) => (
          <circle
            key={fatia.motivo}
            cx={cx}
            cy={cy}
            r={r}
            fill="transparent"
            stroke="var(--danger-500)"
            strokeOpacity={fatia.opacidade}
            strokeWidth={stroke}
            strokeDasharray={`${fatia.dash} ${fatia.gap}`}
            strokeDashoffset={fatia.offset}
          />
        ))}
      </g>
      <text
        x={cx}
        y={cy - 1}
        textAnchor="middle"
        dominantBaseline="middle"
        className="fill-text-primary"
        style={{ font: "600 16px var(--font-sans)" }}
      >
        {total}
      </text>
      <text
        x={cx}
        y={cy + 11}
        textAnchor="middle"
        dominantBaseline="middle"
        className="fill-text-muted"
        style={{ font: "500 5.5px var(--font-sans)", letterSpacing: "0.12em" }}
      >
        PERDAS
      </text>
    </svg>
  )
}

export function obterOpacidadeMotivo(linhas: PerdaPorMotivoLinha[], motivo: MotivoPerda): number {
  const visiveis = ORDEM.map((m) => linhas.find((l) => l.motivo === m)).filter(
    (l): l is PerdaPorMotivoLinha => Boolean(l && l.contagem > 0)
  )
  const idx = visiveis.findIndex((l) => l.motivo === motivo)
  if (idx === -1) return 1
  return OPACIDADE_POR_INDICE[idx] ?? 0.2
}
