"use client"

import { useRouter } from "next/navigation"
import type { EstadoAtendimento, EstadoFiltro } from "@/tipos/atendimentos"
import type { FunilEstadoLinha } from "@/tipos/dashboard"

interface Etapa {
  rotulo: string
  estados: EstadoAtendimento[]
  linkEstado: EstadoFiltro
  largura: number
  cor: string
}

const CAMINHO: Etapa[] = [
  {
    rotulo: "Qualificando",
    estados: ["Novo", "Triagem", "Qualificado"],
    linkEstado: "Qualificando",
    largura: 280,
    cor: "var(--seq-2)",
  },
  {
    rotulo: "Aguardando",
    estados: ["Aguardando_confirmacao", "Confirmado"],
    linkEstado: "Aguardando",
    largura: 220,
    cor: "var(--seq-3)",
  },
  {
    rotulo: "Em atendimento",
    estados: ["Em_execucao"],
    linkEstado: "Em_execucao",
    largura: 160,
    cor: "var(--seq-5)",
  },
  {
    rotulo: "Fechado",
    estados: ["Fechado"],
    linkEstado: "Fechado",
    largura: 120,
    cor: "var(--success-500)",
  },
]

const VBW = 480
const ETAPA_H = 32
const VBH = CAMINHO.length * ETAPA_H
const CX = 240
const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

interface Props {
  linhas: FunilEstadoLinha[]
  total: number
}

export function FunilPipeline({ linhas, total }: Props) {
  const router = useRouter()
  const mapa = new Map(linhas.map((l) => [l.estado, l.contagem]))

  return (
    <svg
      viewBox={`0 0 ${VBW} ${VBH}`}
      role="img"
      aria-label="Funil de atendimentos por estado"
      className="w-full"
    >
      {CAMINHO.map((etapa, i) => {
        const proxLargura = i < CAMINHO.length - 1 ? CAMINHO[i + 1].largura : etapa.largura
        const yTop = i * ETAPA_H
        const yBot = yTop + ETAPA_H
        const xTopLeft = CX - etapa.largura / 2
        const xTopRight = CX + etapa.largura / 2
        const xBotLeft = CX - proxLargura / 2
        const xBotRight = CX + proxLargura / 2
        const path = `M${xTopLeft},${yTop} L${xTopRight},${yTop} L${xBotRight},${yBot - 1} L${xBotLeft},${yBot - 1} Z`
        const contagem = etapa.estados.reduce((soma, e) => soma + (mapa.get(e) ?? 0), 0)
        const pct = total > 0 ? (contagem / total) * 100 : 0
        const yMid = yTop + ETAPA_H / 2

        return (
          <g
            key={etapa.rotulo}
            role="button"
            tabIndex={0}
            aria-label={`${etapa.rotulo}: ${contagem} atendimentos`}
            onClick={() =>
              router.push(`/atendimentos?estado=${encodeURIComponent(etapa.linkEstado)}`)
            }
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault()
                router.push(`/atendimentos?estado=${encodeURIComponent(etapa.linkEstado)}`)
              }
            }}
            className="cursor-pointer outline-none focus-visible:[&_path]:stroke-ring focus-visible:[&_path]:stroke-2 [&_path]:transition-opacity hover:[&_path]:opacity-90"
          >
            <path d={path} fill={etapa.cor} />
            <text
              x={115}
              y={yMid}
              dominantBaseline="middle"
              textAnchor="end"
              className="fill-text-primary"
              style={{ font: "500 12px var(--font-sans)" }}
            >
              {etapa.rotulo}
            </text>
            <text
              x={372}
              y={yMid}
              dominantBaseline="middle"
              textAnchor="start"
              className="fill-text-primary"
              style={{ font: "500 13px var(--font-mono)", fontVariantNumeric: "tabular-nums" }}
            >
              {contagem}
            </text>
            <text
              x={420}
              y={yMid}
              dominantBaseline="middle"
              textAnchor="start"
              className="fill-text-muted"
              style={{ font: "500 11px var(--font-mono)", fontVariantNumeric: "tabular-nums" }}
            >
              {`${PCT_FMT.format(pct)}%`}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
