"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import { ShieldCheck } from "lucide-react"
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RechartsTooltip } from "recharts"
import type {
  MotivoEscaladaPorTipo,
  MotivosEscalada,
  TipoEscalada,
} from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { rotuloTipoEscalada } from "./utils"

interface Props {
  data: MotivosEscalada
  onAbrirTodas: () => void
}

const TIPOS_CANONICOS: TipoEscalada[] = [
  "pix_validado",
  "pix_duvidoso",
  "foto_portaria",
  "aviso_saida",
  "fora_de_oferta",
  "comportamento_atipico",
  "indisponibilidade",
  "cliente_busca",
  "video_chamada",
  "outro",
]

// Paleta categórica da marca (--chart-*): cor fixa e distinta por tipo de escalada.
const COR_POR_TIPO: Record<TipoEscalada, string> = {
  pix_validado: "var(--chart-3)",
  pix_duvidoso: "var(--chart-5)",
  foto_portaria: "var(--chart-2)",
  aviso_saida: "var(--chart-6)",
  fora_de_oferta: "var(--chart-1)",
  comportamento_atipico: "var(--chart-4)",
  indisponibilidade: "var(--chart-7)",
  cliente_busca: "var(--chart-2)",
  video_chamada: "var(--chart-5)",
  outro: "var(--text-muted)",
}

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

interface DadoDonut {
  tipo: TipoEscalada
  rotulo: string
  contagem: number
  pct: number
  cor: string
}

export function BlocoMotivosEscalada({ data, onAbrirTodas }: Props) {
  const router = useRouter()

  const dados = useMemo<DadoDonut[]>(() => {
    let linhas: MotivoEscaladaPorTipo[]
    if (data.por_tipo && data.por_tipo.length > 0) {
      const mapa = new Map(data.por_tipo.map((l) => [l.tipo, l]))
      linhas = TIPOS_CANONICOS.map((tipo) => {
        const existente = mapa.get(tipo)
        if (existente) return existente
        return {
          tipo,
          rotulo: rotuloTipoEscalada(tipo),
          contagem: 0,
          por_modelo: [],
        }
      })
    } else {
      // Fallback: backend antigo só devolve top5 com string livre.
      linhas = data.top5.map((l) => ({
        tipo: (l.tipo ?? "outro") as TipoEscalada,
        rotulo: l.motivo,
        contagem: l.contagem,
        por_modelo: [],
      }))
    }

    const total = data.total > 0 ? data.total : 1
    return linhas
      .map((l) => ({
        tipo: l.tipo,
        rotulo: l.rotulo,
        contagem: l.contagem,
        pct: (l.contagem / total) * 100,
        cor: COR_POR_TIPO[l.tipo] ?? "var(--text-muted)",
      }))
      .sort((a, b) => b.contagem - a.contagem)
  }, [data])

  const dadosVisiveis = dados.filter((d) => d.contagem > 0)

  const navegarParaTipo = (tipo: TipoEscalada) =>
    router.push(`/atendimentos?ia_pausada=true&motivo_escalada=${encodeURIComponent(tipo)}`)

  return (
    <section aria-label="Motivos de escalada" className="flex flex-col gap-3">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Motivos de escalada
        </h2>
        <span className="text-xs font-medium text-text-muted">
          <span className="font-mono tabular-nums">{data.total}</span> no período
        </span>
      </header>
      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {data.total === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
            <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
              <ShieldCheck size={22} strokeWidth={1.75} className="text-text-muted" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-medium text-text-primary">
                Sem atendimentos escalados no período.
              </p>
              <p className="mt-1 text-[13px] text-text-muted">
                Escaladas para Fernando ou modelo aparecem aqui.
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
                        key={d.tipo}
                        fill={d.cor}
                        style={{ cursor: "pointer", outline: "none" }}
                        onClick={() => navegarParaTipo(d.tipo)}
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
                  {data.total}
                </span>
                <span className="text-[11px] text-text-muted">escaladas</span>
              </div>
            </div>

            <ul className="flex flex-col gap-1">
              {dados.map((d) => {
                const inativo = d.contagem === 0
                return (
                  <li key={d.tipo}>
                    <button
                      type="button"
                      onClick={inativo ? undefined : () => navegarParaTipo(d.tipo)}
                      disabled={inativo}
                      className={cn(
                        "grid w-full grid-cols-[14px_1fr_36px_52px] items-center gap-2 rounded-md py-1 pl-1 pr-2 text-left",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                        inativo ? "opacity-50" : "transition-colors hover:bg-accent"
                      )}
                      aria-label={`${d.rotulo}: ${d.contagem} escalas`}
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
                        title={d.rotulo}
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

        {data.total > 0 ? (
          <div className="mt-3 flex items-center justify-end border-t border-foreground/5 pt-3">
            <button
              type="button"
              onClick={onAbrirTodas}
              className="text-xs font-medium text-text-muted underline-offset-2 hover:text-text-primary hover:underline focus-visible:text-text-primary focus-visible:underline focus-visible:outline-none"
            >
              Ver lista completa
            </button>
          </div>
        ) : null}
      </div>
    </section>
  )
}
