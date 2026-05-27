"use client"

import { useMemo } from "react"

interface Props {
  valores: number[]
  cor?: string
  alturaPx?: number
  preencher?: boolean
  rotuloAcessivel?: string
}

// Microchart SVG puro — evita o peso do recharts em algo que não precisa de
// eixos nem tooltip. Usado para dar contexto ao delta dos KPIs (padrão
// Stripe/Linear/Vercel: cada métrica primária mostra a tendência ao lado do
// valor).
export function Sparkline({
  valores,
  cor = "var(--text-secondary)",
  alturaPx = 28,
  preencher = true,
  rotuloAcessivel,
}: Props) {
  const calc = useMemo(() => {
    const limpos = valores.filter((v) => Number.isFinite(v))
    if (limpos.length < 2) return null
    const largura = 100
    const altura = alturaPx
    const max = Math.max(...limpos)
    const min = Math.min(...limpos)
    const range = max - min || Math.max(Math.abs(max), 1)
    const stepX = largura / (limpos.length - 1)
    const pts = limpos.map((v, i) => {
      const x = i * stepX
      const y = altura - ((v - min) / range) * altura
      return [x, Number.isFinite(y) ? y : altura / 2] as const
    })
    const line = pts
      .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
      .join(" ")
    const area = `${line} L${largura.toFixed(2)},${altura.toFixed(2)} L0,${altura.toFixed(2)} Z`
    const ultimo = pts[pts.length - 1]
    return { line, area, largura, altura, ultimo }
  }, [valores, alturaPx])

  if (!calc) {
    return <div aria-hidden style={{ height: alturaPx }} className="w-full" />
  }

  return (
    <svg
      role="img"
      aria-label={rotuloAcessivel ?? "Tendência no período"}
      viewBox={`0 0 ${calc.largura} ${calc.altura}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height: alturaPx, display: "block" }}
    >
      {preencher && <path d={calc.area} fill={cor} fillOpacity={0.1} />}
      <path
        d={calc.line}
        fill="none"
        stroke={cor}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={calc.ultimo[0]}
        cy={calc.ultimo[1]}
        r={1.6}
        fill={cor}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
