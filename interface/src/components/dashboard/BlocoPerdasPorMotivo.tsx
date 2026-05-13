"use client"

import { useRouter } from "next/navigation"
import { CheckCircle2 } from "lucide-react"
import type { MotivoPerda } from "@/tipos/atendimentos"
import type { PerdaPorMotivoLinha } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { N_MINIMO_PARA_DELTA_PCT } from "./utils"

const ROTULOS: Record<MotivoPerda, string> = {
  preco: "Preço",
  sumiu: "Sumiu",
  risco: "Risco",
  indisponibilidade: "Indisponibilidade",
  fora_de_area: "Fora da área",
  outro: "Outro",
}

const ORDEM_CANONICA: MotivoPerda[] = [
  "sumiu",
  "preco",
  "risco",
  "indisponibilidade",
  "fora_de_area",
  "outro",
]

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

interface Props {
  linhas: PerdaPorMotivoLinha[]
  totalPerdas: number
  totalDecididos?: number
}

export function BlocoPerdasPorMotivo({ linhas, totalPerdas, totalDecididos }: Props) {
  const router = useRouter()
  const mapa = new Map(linhas.map((l) => [l.motivo, l.contagem]))

  const dados = ORDEM_CANONICA.map((motivo) => ({
    motivo,
    contagem: mapa.get(motivo) ?? 0,
    pct: totalPerdas > 0 ? ((mapa.get(motivo) ?? 0) / totalPerdas) * 100 : 0,
  })).sort((a, b) => b.contagem - a.contagem)

  const maximo = Math.max(...dados.map((d) => d.contagem), 1)
  const amostraPequena = totalPerdas > 0 && totalPerdas < N_MINIMO_PARA_DELTA_PCT
  const pctDecididos =
    totalDecididos !== undefined && totalDecididos > 0 ? (totalPerdas / totalDecididos) * 100 : null

  // Pareto: marca dos 80% acumulados (referência clássica).
  let acumulado = 0
  const ate80 = new Set<MotivoPerda>()
  for (const linha of dados) {
    if (totalPerdas === 0) break
    if (acumulado < 80) ate80.add(linha.motivo)
    acumulado += linha.pct
  }

  return (
    <section aria-label="Perdas por motivo" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Perdas por motivo</h2>
        <span className="text-xs font-medium text-text-muted">
          {totalPerdas} perdas
          {pctDecididos !== null ? (
            <>
              {" · "}
              <span className="font-mono tabular-nums">
                {totalPerdas}/{totalDecididos} dos decididos ({PCT_FMT.format(pctDecididos)}%)
              </span>
            </>
          ) : null}
          {amostraPequena ? (
            <span className="ml-2 inline-flex items-center rounded-full bg-ink-100 px-2 py-0.5 font-mono text-[10px] text-text-muted">
              amostra pequena
            </span>
          ) : null}
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {totalPerdas === 0 ? (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={20} strokeWidth={1.5} className="text-success-500" aria-hidden />
            <span className="text-sm text-text-primary">Sem perdas no período.</span>
          </div>
        ) : (
          <ul className="flex flex-col gap-1">
            {dados.map((linha) => {
              const pctBarra = (linha.contagem / maximo) * 100
              const inativo = linha.contagem === 0
              const noTopo = ate80.has(linha.motivo) && linha.contagem > 0
              const handleClick = inativo
                ? undefined
                : () =>
                    router.push(
                      `/atendimentos?estado=Perdido&motivo_perda=${encodeURIComponent(linha.motivo)}`
                    )
              return (
                <li key={linha.motivo}>
                  <button
                    type="button"
                    onClick={handleClick}
                    disabled={inativo}
                    className={cn(
                      "grid w-full grid-cols-[140px_1fr_40px_56px] items-center gap-3 rounded-md py-1.5 pl-2 pr-3 text-left",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      inativo ? "opacity-50" : "transition-colors hover:bg-ink-200"
                    )}
                    aria-label={`${ROTULOS[linha.motivo]}: ${linha.contagem} perdas`}
                  >
                    <span
                      className={cn(
                        "truncate text-[13px]",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {ROTULOS[linha.motivo]}
                    </span>
                    <div className="relative h-2.5 overflow-hidden rounded-full bg-ink-100">
                      <div
                        className="h-full rounded-full transition-[width] duration-300"
                        style={{
                          width: `${pctBarra}%`,
                          background: noTopo ? "var(--danger-500)" : "var(--text-muted)",
                          opacity: noTopo ? 1 : 0.55,
                        }}
                      />
                    </div>
                    <span
                      className={cn(
                        "text-right font-mono text-xs font-medium tabular-nums",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {linha.contagem}
                    </span>
                    <span className="text-right text-xs font-medium text-text-muted tabular-nums">
                      {`${PCT_FMT.format(linha.pct)}%`}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
