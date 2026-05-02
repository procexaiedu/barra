"use client"

import { useRouter } from "next/navigation"
import { TrendingDown } from "lucide-react"
import type { FunilEstadoLinha } from "@/tipos/dashboard"
import { FunilPipeline } from "./FunilPipeline"

interface Props {
  linhas: FunilEstadoLinha[]
}

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function FunilEstados({ linhas }: Props) {
  const router = useRouter()
  const total = linhas.reduce((soma, linha) => soma + linha.contagem, 0)
  const mapa = new Map(linhas.map((l) => [l.estado, l.contagem]))
  const perdido = mapa.get("Perdido") ?? 0
  const pctPerdido = total > 0 ? (perdido / total) * 100 : 0

  return (
    <section
      aria-label="Volume por estado"
      className="flex flex-col gap-3"
    >
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Volume por estado</h2>
        <span className="text-xs font-medium text-text-muted">
          {total} atendimentos no período
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {total === 0 ? (
          <div className="flex flex-col gap-1 rounded-md bg-ink-200 p-4">
            <span className="text-sm text-text-primary">Nenhum atendimento no período selecionado.</span>
            <span className="text-[13px] text-text-muted">Ajuste o período no topo da página.</span>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                Caminho até fechamento
              </p>
              <div className="mx-auto w-full max-w-[640px]">
                <FunilPipeline linhas={linhas} total={total} />
              </div>
            </div>

            <button
              type="button"
              onClick={() => router.push("/atendimentos?estado=Perdido")}
              className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-md border-l-2 border-danger-500 bg-danger-500/8 px-4 py-3 text-left transition-colors hover:bg-danger-500/12 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              aria-label={`Saídas perdidas: ${perdido} atendimentos`}
            >
              <TrendingDown size={18} strokeWidth={1.75} className="text-danger-500" aria-hidden />
              <div className="flex flex-col">
                <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                  Saídas perdidas
                </span>
                <span className="text-[13px] text-text-primary">
                  Atendimentos encerrados antes do fechamento
                </span>
              </div>
              <div className="flex items-baseline gap-2 font-mono tabular-nums">
                <span className="text-2xl font-medium text-danger-500">{perdido}</span>
                <span className="text-xs text-text-muted">{`${PCT_FMT.format(pctPerdido)}%`}</span>
              </div>
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
