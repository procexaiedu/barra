"use client"

import { useRouter } from "next/navigation"
import { ChevronRight } from "lucide-react"
import type { ProfissionalRanking } from "@/tipos/dashboard"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import { formatPercent } from "./utils"

interface Props {
  profissionais: ProfissionalRanking[]
}

export function ProfissionaisRanking({ profissionais }: Props) {
  const router = useRouter()
  const volumeMaximo = Math.max(...profissionais.map((p) => p.volume), 0)

  if (profissionais.length === 0) {
    return (
      <section
        aria-label="Profissionais mais procuradas"
        className="flex flex-col gap-3"
      >
        <header>
          <h2 className="text-base font-semibold text-text-primary">
            Profissionais mais procuradas
          </h2>
        </header>
        <div className="flex flex-col items-start gap-3 rounded-lg bg-card p-6 ring-1 ring-foreground/10">
          <p className="text-sm text-text-muted">Nenhuma modelo cadastrada.</p>
          <Button variant="secondary" size="lg" onClick={() => router.push("/modelos")}>
            Cadastrar modelo →
          </Button>
        </div>
      </section>
    )
  }

  return (
    <section
      aria-label="Profissionais mais procuradas"
      className="flex flex-col gap-3"
    >
      <header>
        <h2 className="text-base font-semibold text-text-primary">
          Profissionais mais procuradas
        </h2>
      </header>
      <div className="overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Profissionais ordenadas por volume no período</caption>
          <thead>
            <tr className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
              <th className="px-4 py-3 text-left">Modelo</th>
              <th className="w-44 px-4 py-3 text-right">Volume</th>
              <th className="w-32 px-4 py-3 text-right">Fechamentos</th>
              <th className="w-40 px-4 py-3 text-right">Valor bruto</th>
              <th className="w-24 px-4 py-3 text-right">Conversão</th>
              <th className="w-6 px-2 py-3" aria-hidden />
            </tr>
          </thead>
          <tbody>
            {profissionais.map((p, idx) => {
              const pctVolume = volumeMaximo > 0 ? (p.volume / volumeMaximo) * 100 : 0
              return (
                <tr
                  key={p.modelo.id}
                  onClick={() => router.push(`/modelos?modelo=${p.modelo.id}&aba=perfil`)}
                  tabIndex={0}
                  role="link"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      router.push(`/modelos?modelo=${p.modelo.id}&aba=perfil`)
                    }
                  }}
                  className="cursor-pointer border-t border-border/60 transition-colors hover:bg-ink-200 focus:bg-ink-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                >
                  <td className="px-4 py-4 align-middle">
                    <div className="flex items-baseline gap-3">
                      <span className="font-mono text-xs text-text-muted">#{idx + 1}</span>
                      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-text-primary">
                        {p.modelo.nome}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-4 align-middle">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        aria-hidden
                        className="block h-1.5 w-20 overflow-hidden rounded-sm bg-ink-300"
                      >
                        <span
                          className="block h-full rounded-sm bg-gold-500 transition-[width]"
                          style={{ width: `${pctVolume}%` }}
                        />
                      </span>
                      <span className="font-mono text-xs text-text-primary tabular-nums">
                        {p.volume}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs text-success-500 tabular-nums">
                    {p.fechamentos}
                  </td>
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs text-text-primary tabular-nums">
                    {formatBRL(p.valor_bruto_brl)}
                  </td>
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs text-text-primary tabular-nums">
                    {formatPercent(p.taxa_conversao_pct)}
                  </td>
                  <td className="px-2 py-4 text-right align-middle">
                    <ChevronRight size={16} strokeWidth={1.5} className="text-text-muted" aria-hidden />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
