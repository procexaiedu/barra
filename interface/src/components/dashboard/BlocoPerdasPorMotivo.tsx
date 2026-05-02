"use client"

import { useRouter } from "next/navigation"
import { CheckCircle2 } from "lucide-react"
import type { MotivoPerda } from "@/tipos/atendimentos"
import type { PerdaPorMotivoLinha } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { DonutPerdas, obterOpacidadeMotivo } from "./DonutPerdas"

const ROTULOS: Record<MotivoPerda, string> = {
  preco: "Preço",
  sumiu: "Sumiu",
  risco: "Risco",
  indisponibilidade: "Indisponibilidade",
  fora_de_area: "Fora da área",
  outro: "Outro",
}

const ORDEM: MotivoPerda[] = [
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
}

export function BlocoPerdasPorMotivo({ linhas, totalPerdas }: Props) {
  const router = useRouter()
  const visiveis = ORDEM.map((motivo) => linhas.find((l) => l.motivo === motivo)).filter(
    (l): l is PerdaPorMotivoLinha => Boolean(l && l.contagem > 0)
  )

  return (
    <section
      aria-label="Perdas por motivo"
      className="flex flex-col gap-3"
    >
      <header>
        <h2 className="text-base font-semibold text-text-primary">Perdas por motivo</h2>
      </header>
      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {totalPerdas === 0 ? (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={20} strokeWidth={1.5} className="text-success-500" aria-hidden />
            <span className="text-sm text-text-primary">Sem perdas no período.</span>
          </div>
        ) : (
          <div className="flex flex-col items-stretch gap-6 sm:flex-row sm:items-center">
            <div className="flex justify-center sm:justify-start">
              <DonutPerdas linhas={visiveis} total={totalPerdas} />
            </div>
            <ul className="flex w-full flex-col">
              {visiveis.map((linha) => {
                const pct = totalPerdas > 0 ? (linha.contagem / totalPerdas) * 100 : 0
                const opacidade = obterOpacidadeMotivo(visiveis, linha.motivo)
                const handleClick = () =>
                  router.push(
                    `/atendimentos?estado=Perdido&motivo_perda=${encodeURIComponent(linha.motivo)}`
                  )
                return (
                  <li key={linha.motivo}>
                    <button
                      type="button"
                      onClick={handleClick}
                      className={cn(
                        "grid h-8 w-full grid-cols-[14px_1fr_40px_56px] items-center gap-3 rounded-md text-left",
                        "transition-colors hover:bg-ink-200",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      )}
                      aria-label={`${ROTULOS[linha.motivo]}: ${linha.contagem} perdas`}
                    >
                      <span
                        aria-hidden
                        className="ml-1 block h-2.5 w-2.5 rounded-sm bg-danger-500"
                        style={{ opacity: opacidade }}
                      />
                      <span className="truncate text-[13px] text-text-primary">
                        {ROTULOS[linha.motivo]}
                      </span>
                      <span className="text-right font-mono text-xs font-medium text-text-primary tabular-nums">
                        {linha.contagem}
                      </span>
                      <span className="text-right text-xs font-medium text-text-muted tabular-nums">
                        {`${PCT_FMT.format(pct)}%`}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
