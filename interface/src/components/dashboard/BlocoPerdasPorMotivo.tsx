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

// Paleta categórica da marca (--chart-*): cor fixa e distinta por motivo.
// Verde (--chart-3) fica de fora de propósito — "verde = bom" destoa de uma perda.
const COR_POR_MOTIVO: Record<MotivoPerda, string> = {
  sumiu: "var(--chart-2)",
  preco: "var(--chart-1)",
  risco: "var(--chart-5)",
  indisponibilidade: "var(--chart-4)",
  fora_de_area: "var(--chart-6)",
  outro: "var(--text-muted)",
}

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
  cor: string
}

export function BlocoPerdasPorMotivo({ linhas, totalPerdas, totalDecididos }: Props) {
  const router = useRouter()

  const dados = useMemo<DadoDonut[]>(() => {
    const mapa = new Map(linhas.map((l) => [l.motivo, l.contagem]))
    return ORDEM_CANONICA.map((motivo) => ({
      motivo,
      rotulo: ROTULOS[motivo],
      contagem: mapa.get(motivo) ?? 0,
      pct: totalPerdas > 0 ? ((mapa.get(motivo) ?? 0) / totalPerdas) * 100 : 0,
      cor: COR_POR_MOTIVO[motivo],
    })).sort((a, b) => b.contagem - a.contagem)
  }, [linhas, totalPerdas])

  const amostraPequena = totalPerdas > 0 && totalPerdas < N_MINIMO_PARA_DELTA_PCT
  const pctDecididos =
    totalDecididos !== undefined && totalDecididos > 0 ? (totalPerdas / totalDecididos) * 100 : null

  const dadosVisiveis = dados.filter((d) => d.contagem > 0)

  return (
    <section aria-label="Perdas por motivo" className="flex flex-col gap-3">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Perdas por motivo
        </h2>
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
            <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-text-muted">
              amostra pequena
            </span>
          ) : null}
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {totalPerdas === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
            <div className="flex size-11 items-center justify-center rounded-full bg-success-500/10 ring-1 ring-success-500/20">
              <CheckCircle2 size={22} strokeWidth={1.75} className="text-success-500" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-medium text-text-primary">Sem perdas no período.</p>
              <p className="mt-1 text-[13px] text-text-muted">
                Os motivos de perda aparecem aqui quando houver atendimentos perdidos.
              </p>
            </div>
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
                        fill={d.cor}
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
                        inativo ? "opacity-50" : "transition-colors hover:bg-accent"
                      )}
                      aria-label={`${d.rotulo}: ${d.contagem} perdas`}
                    >
                      <span
                        aria-hidden
                        className="inline-block h-2.5 w-2.5 rounded-sm"
                        style={{ background: d.cor }}
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
