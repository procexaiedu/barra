"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import { CheckCircle2 } from "lucide-react"
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RechartsTooltip } from "recharts"
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

interface DadoDonut {
  motivo: MotivoPerda
  rotulo: string
  contagem: number
  pct: number
  noTopo: boolean
}

export function BlocoPerdasPorMotivo({ linhas, totalPerdas, totalDecididos }: Props) {
  const router = useRouter()

  const dados = useMemo<DadoDonut[]>(() => {
    const mapa = new Map(linhas.map((l) => [l.motivo, l.contagem]))
    const ordenado = ORDEM_CANONICA.map((motivo) => ({
      motivo,
      rotulo: ROTULOS[motivo],
      contagem: mapa.get(motivo) ?? 0,
      pct: totalPerdas > 0 ? ((mapa.get(motivo) ?? 0) / totalPerdas) * 100 : 0,
    })).sort((a, b) => b.contagem - a.contagem)

    // Pareto: marca dos 80% acumulados.
    let acumulado = 0
    const ate80 = new Set<MotivoPerda>()
    for (const linha of ordenado) {
      if (totalPerdas === 0) break
      if (acumulado < 80) ate80.add(linha.motivo)
      acumulado += linha.pct
    }

    return ordenado.map((l) => ({ ...l, noTopo: ate80.has(l.motivo) }))
  }, [linhas, totalPerdas])

  const amostraPequena = totalPerdas > 0 && totalPerdas < N_MINIMO_PARA_DELTA_PCT
  const pctDecididos =
    totalDecididos !== undefined && totalDecididos > 0 ? (totalPerdas / totalDecididos) * 100 : null

  const dadosVisiveis = dados.filter((d) => d.contagem > 0)

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
          <div className="grid grid-cols-1 items-center gap-4 sm:grid-cols-[200px_1fr] lg:grid-cols-[240px_1fr]">
            <div className="relative mx-auto h-[200px] w-[200px] lg:h-[240px] lg:w-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={dadosVisiveis}
                    dataKey="contagem"
                    nameKey="rotulo"
                    innerRadius="62%"
                    outerRadius="100%"
                    paddingAngle={dadosVisiveis.length > 1 ? 2 : 0}
                    stroke="var(--card)"
                    strokeWidth={2}
                    isAnimationActive={false}
                  >
                    {dadosVisiveis.map((d) => (
                      <Cell
                        key={d.motivo}
                        fill={d.noTopo ? "var(--danger-500)" : "var(--text-muted)"}
                        fillOpacity={d.noTopo ? 1 : 0.5}
                        style={{ cursor: "pointer", outline: "none" }}
                        onClick={() =>
                          router.push(
                            `/atendimentos?estado=Perdido&motivo_perda=${encodeURIComponent(d.motivo)}`
                          )
                        }
                      />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    wrapperStyle={{ outline: "none" }}
                    contentStyle={{
                      background: "var(--card)",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      padding: "4px 8px",
                      fontSize: 12,
                    }}
                    formatter={(value, _name, item) => {
                      const p = (item as { payload?: DadoDonut })?.payload
                      const pct = p ? PCT_FMT.format(p.pct) : "0"
                      return [`${value} (${pct}%)`, p?.rotulo ?? ""]
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="font-mono text-2xl font-semibold tabular-nums text-text-primary">
                  {totalPerdas}
                </span>
                <span className="text-[11px] text-text-muted">perdas</span>
              </div>
            </div>

            <ul className="flex flex-col gap-1">
              {dados.map((d) => {
                const inativo = d.contagem === 0
                const handleClick = inativo
                  ? undefined
                  : () =>
                      router.push(
                        `/atendimentos?estado=Perdido&motivo_perda=${encodeURIComponent(d.motivo)}`
                      )
                return (
                  <li key={d.motivo}>
                    <button
                      type="button"
                      onClick={handleClick}
                      disabled={inativo}
                      className={cn(
                        "grid w-full grid-cols-[14px_1fr_36px_52px] items-center gap-2 rounded-md py-1 pl-1 pr-2 text-left",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                        inativo ? "opacity-50" : "transition-colors hover:bg-ink-200"
                      )}
                      aria-label={`${d.rotulo}: ${d.contagem} perdas`}
                    >
                      <span
                        aria-hidden
                        className="inline-block h-2.5 w-2.5 rounded-sm"
                        style={{
                          background: d.noTopo ? "var(--danger-500)" : "var(--text-muted)",
                          opacity: d.noTopo ? 1 : 0.55,
                        }}
                      />
                      <span
                        className={cn(
                          "truncate text-[13px]",
                          inativo ? "text-text-muted" : "text-text-primary"
                        )}
                      >
                        {d.rotulo}
                      </span>
                      <span
                        className={cn(
                          "text-right font-mono text-xs font-medium tabular-nums",
                          inativo ? "text-text-muted" : "text-text-primary"
                        )}
                      >
                        {d.contagem}
                      </span>
                      <span className="text-right text-xs text-text-muted tabular-nums">
                        {PCT_FMT.format(d.pct)}%
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
