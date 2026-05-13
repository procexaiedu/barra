"use client"

import { useRouter } from "next/navigation"
import type { EstadoAtendimento, EstadoFiltro } from "@/tipos/atendimentos"
import type { FunilEstadoLinha } from "@/tipos/dashboard"

interface Etapa {
  rotulo: string
  estados: EstadoAtendimento[]
  linkEstado: EstadoFiltro
  cor: string
}

const CAMINHO: Etapa[] = [
  {
    rotulo: "Qualificando",
    estados: ["Novo", "Triagem", "Qualificado"],
    linkEstado: "Qualificando",
    cor: "var(--seq-2)",
  },
  {
    rotulo: "Aguardando",
    estados: ["Aguardando_confirmacao", "Confirmado"],
    linkEstado: "Aguardando",
    cor: "var(--seq-3)",
  },
  {
    rotulo: "Em atendimento",
    estados: ["Em_execucao"],
    linkEstado: "Em_execucao",
    cor: "var(--seq-5)",
  },
  {
    rotulo: "Fechado",
    estados: ["Fechado"],
    linkEstado: "Fechado",
    cor: "var(--success-500)",
  },
]

const VBW = 480
const ETAPA_H = 32
const VBH = CAMINHO.length * ETAPA_H
const CX = 240
const LARGURA_MAX = 320
const LARGURA_MIN_VISIVEL = 64
const LARGURA_ZERO = 8
const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

function calcularLargura(contagem: number, contagemMax: number): number {
  if (contagem === 0) return LARGURA_ZERO
  const proporcao = contagem / contagemMax
  return Math.max(LARGURA_MIN_VISIVEL, proporcao * LARGURA_MAX)
}

interface Props {
  linhas: FunilEstadoLinha[]
  total: number
}

export function FunilPipeline({ linhas, total }: Props) {
  const router = useRouter()
  const mapa = new Map(linhas.map((l) => [l.estado, l.contagem]))

  const etapasComContagem = CAMINHO.map((etapa) => ({
    etapa,
    contagem: etapa.estados.reduce((soma, e) => soma + (mapa.get(e) ?? 0), 0),
  }))
  const contagemMax = Math.max(...etapasComContagem.map((e) => e.contagem), 1)
  const etapasCalculadas = etapasComContagem.map((item, i) => ({
    ...item,
    largura: calcularLargura(item.contagem, contagemMax),
    conversao:
      i === 0
        ? null
        : etapasComContagem[i - 1].contagem === 0
          ? 0
          : Math.round((item.contagem / etapasComContagem[i - 1].contagem) * 100),
  }))

  return (
    <svg
      viewBox={`0 0 ${VBW} ${VBH}`}
      role="img"
      aria-label="Funil de atendimentos por estado"
      className="w-full"
    >
      {etapasCalculadas.map(({ etapa, contagem, largura, conversao }, i) => {
        const proxLargura = i < etapasCalculadas.length - 1 ? etapasCalculadas[i + 1].largura : largura
        const yTop = i * ETAPA_H
        const yBot = yTop + ETAPA_H
        const xTopLeft = CX - largura / 2
        const xTopRight = CX + largura / 2
        const xBotLeft = CX - proxLargura / 2
        const xBotRight = CX + proxLargura / 2
        const path = `M${xTopLeft},${yTop} L${xTopRight},${yTop} L${xBotRight},${yBot - 1} L${xBotLeft},${yBot - 1} Z`
        const pct = total > 0 ? (contagem / total) * 100 : 0
        const yMid = yTop + ETAPA_H / 2
        const tituloLinhas = [`${etapa.rotulo}: ${contagem}`]
        if (conversao !== null) {
          tituloLinhas.push(`Conversão da etapa anterior: ${conversao}%`)
        }
        tituloLinhas.push(`${PCT_FMT.format(pct)}% do total no período`)

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
            <title>{tituloLinhas.join("\n")}</title>
            <path d={path} fill={etapa.cor} opacity={contagem === 0 ? 0.4 : 1} />
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
