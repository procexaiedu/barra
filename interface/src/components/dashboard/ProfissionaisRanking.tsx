"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { ChevronRight, Plus, Users } from "lucide-react"
import type { ProfissionalRanking } from "@/tipos/dashboard"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import { N_MINIMO_PARA_DELTA_PCT, formatPercent } from "./utils"
import { cn } from "@/lib/utils"

interface Props {
  profissionais: ProfissionalRanking[]
  modeloIdsSelecionadas: string[]
}

export function ProfissionaisRanking({ profissionais, modeloIdsSelecionadas }: Props) {
  const router = useRouter()
  const volumeMaximo = Math.max(...profissionais.map((p) => p.volume), 0)
  const selecionadas = new Set(modeloIdsSelecionadas)
  const temSelecao = modeloIdsSelecionadas.length > 0

  if (profissionais.length === 0) {
    return (
      <section
        aria-label="Profissionais mais procuradas"
        className="flex flex-col gap-3"
      >
        <header>
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Profissionais mais procuradas
          </h2>
        </header>
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg bg-card px-6 py-10 text-center ring-1 ring-foreground/10">
          <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
            <Users size={22} strokeWidth={1.75} className="text-text-muted" aria-hidden />
          </div>
          <div>
            <p className="text-sm font-medium text-text-primary">Nenhuma modelo cadastrada.</p>
            <p className="mt-1 text-[13px] text-text-muted">
              Cadastre uma modelo para ver o ranking de procura.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => router.push("/modelos")}>
            <Plus size={14} strokeWidth={1.5} />
            Cadastrar modelo
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
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Profissionais mais procuradas
        </h2>
      </header>
      {/* Mobile: cards (a tabela de 8 colunas não cabe em telas estreitas) */}
      <ul className="flex flex-col gap-2 md:hidden">
        {profissionais.map((p, idx) => {
          const pctVolume = volumeMaximo > 0 ? (p.volume / volumeMaximo) * 100 : 0
          const destacada = temSelecao && selecionadas.has(p.modelo.id)
          const n = p.n_referencia ?? p.fechamentos + (p.perdas ?? 0)
          return (
            <li
              key={p.modelo.id}
              className={cn(
                "relative rounded-lg bg-card p-3 ring-1 ring-foreground/10",
                destacada && "ring-text-brand/40",
                temSelecao && !destacada && "opacity-55"
              )}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-text-muted">#{idx + 1}</span>
                <span
                  className={cn(
                    "text-xs font-semibold uppercase tracking-[0.08em]",
                    destacada ? "text-text-brand" : "text-text-primary"
                  )}
                >
                  {p.modelo.nome}
                </span>
                {idx === 0 && (
                  <span className="rounded-sm bg-text-brand/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-brand">
                    Top
                  </span>
                )}
                <Link
                  href={`/modelos?modelo=${p.modelo.id}&aba=perfil`}
                  aria-label={`Abrir perfil de ${p.modelo.nome}`}
                  className="ml-auto inline-flex rounded-sm text-text-muted transition-colors after:absolute after:inset-0 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <ChevronRight size={16} strokeWidth={1.5} aria-hidden />
                </Link>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span aria-hidden className="block h-1.5 flex-1 overflow-hidden rounded-sm bg-muted">
                  <span className="block h-full rounded-sm bg-text-brand" style={{ width: `${pctVolume}%` }} />
                </span>
                <span className="font-mono text-xs text-text-primary tabular-nums">{p.volume} vol.</span>
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs tabular-nums">
                <div className="flex justify-between">
                  <dt className="text-text-muted">Fech.</dt>
                  <dd className="text-success-500">{p.fechamentos}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-text-muted">Conv.</dt>
                  <dd className="text-text-primary">{formatPercent(p.taxa_conversao_pct)} · n={n}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-text-muted">Bruto</dt>
                  <dd className="text-text-primary">{formatBRL(p.valor_bruto_brl)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-text-muted">Líquido</dt>
                  <dd className="text-success-500">{formatBRL(p.valor_liquido_brl)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-text-muted">Repasse</dt>
                  <dd className="text-text-muted">{formatBRL(p.valor_repasse_modelo_brl)}</dd>
                </div>
              </dl>
            </li>
          )
        })}
      </ul>

      {/* Desktop: tabela completa */}
      <div className="hidden overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10 md:block">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Profissionais ordenadas por volume no período</caption>
          <thead>
            <tr className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
              <th className="px-4 py-3 text-left">Modelo</th>
              <th className="w-44 px-4 py-3 text-right">Volume</th>
              <th className="w-32 px-4 py-3 text-right">Fechamentos</th>
              <th className="w-40 px-4 py-3 text-right">Valor bruto</th>
              <th className="w-40 px-4 py-3 text-right">Líquido</th>
              <th className="w-40 px-4 py-3 text-right">Repasse</th>
              <th className="w-24 px-4 py-3 text-right">Conversão</th>
              <th className="w-6 px-2 py-3" aria-hidden />
            </tr>
          </thead>
          <tbody>
            {profissionais.map((p, idx) => {
              const pctVolume = volumeMaximo > 0 ? (p.volume / volumeMaximo) * 100 : 0
              const destacada = temSelecao && selecionadas.has(p.modelo.id)
              return (
                <tr
                  key={p.modelo.id}
                  className={cn(
                    "relative cursor-pointer border-t border-border/60 transition-colors hover:bg-accent has-[a:focus-visible]:bg-accent",
                    destacada && "bg-text-brand/[0.07]",
                    temSelecao && !destacada && "opacity-55"
                  )}
                >
                  <td className="px-4 py-4 align-middle">
                    <div className="flex items-baseline gap-3">
                      <span className="font-mono text-xs text-text-muted">#{idx + 1}</span>
                      <span
                        className={cn(
                          "text-xs font-semibold uppercase tracking-[0.08em]",
                          destacada ? "text-text-brand" : "text-text-primary"
                        )}
                      >
                        {p.modelo.nome}
                      </span>
                      {idx === 0 ? (
                        <span className="rounded-sm bg-text-brand/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-brand">
                          Top
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-4 align-middle">
                    <div className="flex items-center justify-end gap-2">
                      <span
                        aria-hidden
                        className="block h-1.5 w-20 overflow-hidden rounded-sm bg-muted"
                      >
                        <span
                          className="block h-full rounded-sm bg-text-brand"
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
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs text-success-500 tabular-nums">
                    {formatBRL(p.valor_liquido_brl)}
                  </td>
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs text-text-muted tabular-nums">
                    {formatBRL(p.valor_repasse_modelo_brl)}
                  </td>
                  <td className="px-4 py-4 text-right align-middle font-mono text-xs tabular-nums">
                    {(() => {
                      const n = p.n_referencia ?? p.fechamentos + (p.perdas ?? 0)
                      const amostraPequena = n > 0 && n < N_MINIMO_PARA_DELTA_PCT
                      const titulo = amostraPequena
                        ? `Amostra pequena (n=${n}). Conversão tem alta variância.`
                        : `n=${n}`
                      return (
                        <span
                          title={titulo}
                          className={cn(
                            "inline-flex flex-col items-end leading-tight",
                            amostraPequena ? "text-text-muted" : "text-text-primary"
                          )}
                        >
                          <span>{formatPercent(p.taxa_conversao_pct)}</span>
                          <span className="text-[10px] text-text-muted">n={n}</span>
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-2 py-4 text-right align-middle">
                    <Link
                      href={`/modelos?modelo=${p.modelo.id}&aba=perfil`}
                      aria-label={`Abrir perfil de ${p.modelo.nome}`}
                      className="inline-flex rounded-sm text-text-muted transition-colors after:absolute after:inset-0 hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                    >
                      <ChevronRight size={16} strokeWidth={1.5} aria-hidden />
                    </Link>
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
