"use client"

import { useMemo, useRef, useState } from "react"

interface Props {
  valores: number[]
  cor?: string
  alturaPx?: number
  preencher?: boolean
  rotuloAcessivel?: string
  rotulos?: string[]
  formatador?: (n: number) => string
}

// Microchart SVG puro — evita o peso do recharts em algo que não precisa de
// eixos. Padrão Stripe/Linear/Vercel: cada métrica primária mostra a tendência
// ao lado do valor; quando há `rotulos`, exibimos crosshair + tooltip no hover
// para inspecionar o ponto.
export function Sparkline({
  valores,
  cor = "var(--text-secondary)",
  alturaPx = 28,
  preencher = true,
  rotuloAcessivel,
  rotulos,
  formatador,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

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
    return { line, area, largura, altura, ultimo, pts, valoresLimpos: limpos }
  }, [valores, alturaPx])

  if (!calc) {
    return <div aria-hidden style={{ height: alturaPx }} className="w-full" />
  }

  const interativo = Array.isArray(rotulos) && rotulos.length >= calc.pts.length

  const handleMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!interativo || !wrapperRef.current) return
    const rect = wrapperRef.current.getBoundingClientRect()
    if (rect.width <= 0) return
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    const idx = Math.round(ratio * (calc.pts.length - 1))
    setHoverIdx(idx)
  }
  const handleLeave = () => setHoverIdx(null)

  const fmt =
    formatador ?? ((n: number) => new Intl.NumberFormat("pt-BR").format(n))

  const hover =
    hoverIdx !== null && hoverIdx >= 0 && hoverIdx < calc.pts.length
      ? {
          idx: hoverIdx,
          x: calc.pts[hoverIdx][0],
          y: calc.pts[hoverIdx][1],
          xPct: (calc.pts[hoverIdx][0] / calc.largura) * 100,
          valor: calc.valoresLimpos[hoverIdx],
          rotulo: rotulos?.[hoverIdx],
        }
      : null

  return (
    <div
      ref={wrapperRef}
      className="relative w-full"
      style={{ height: alturaPx }}
      onPointerMove={handleMove}
      onPointerLeave={handleLeave}
    >
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
        {hover && (
          <>
            <line
              x1={hover.x}
              x2={hover.x}
              y1={0}
              y2={calc.altura}
              stroke={cor}
              strokeOpacity={0.45}
              strokeWidth={1}
              strokeDasharray="2 2"
              vectorEffect="non-scaling-stroke"
            />
            <circle
              cx={hover.x}
              cy={hover.y}
              r={2.6}
              fill="var(--card)"
              stroke={cor}
              strokeWidth={1.4}
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}
      </svg>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-sm border border-border bg-card px-1.5 py-1 text-[10.5px] leading-tight shadow-md shadow-black/40"
          style={{
            left: `${Math.min(96, Math.max(4, hover.xPct))}%`,
            top: -6,
          }}
        >
          {hover.rotulo && (
            <div className="text-text-muted">{hover.rotulo}</div>
          )}
          <div className="font-medium tabular-nums text-text-primary">
            {fmt(hover.valor)}
          </div>
        </div>
      )}
    </div>
  )
}
