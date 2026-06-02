"use client"

import { useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroMixForma } from "@/tipos/financeiro"
import { ChartShell } from "./ChartReceitaDiaria"

interface Props {
  itens: FinanceiroMixForma[]
}

interface Fatia {
  forma: string
  rotulo: string
  valor: number
  fechamentos: number
  pct: number
  cor: string
}

// Ordem canônica do enum + 'indefinido'. Cor fixa por forma — não permutar
// pra que a mesma forma mantenha o mesmo tom entre períodos/telas.
const ORDEM: Array<{ id: string; rotulo: string; cor: string }> = [
  { id: "pix", rotulo: "Pix", cor: "var(--chart-1)" },
  { id: "dinheiro", rotulo: "Dinheiro", cor: "var(--chart-3)" },
  { id: "cartao", rotulo: "Cartão", cor: "var(--chart-2)" },
  { id: "outro", rotulo: "Outro", cor: "var(--chart-4)" },
  { id: "indefinido", rotulo: "Indefinido", cor: "var(--text-muted)" },
]

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const PCT_FINO = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

export function ChartMixForma({ itens }: Props) {
  const [hover, setHover] = useState<string | null>(null)

  const { fatias, total, ativas } = useMemo(() => {
    const total = itens.reduce((acc, x) => acc + x.valor_bruto, 0)
    const mapa = new Map(itens.map((x) => [x.forma_pagamento, x]))
    const fatias = ORDEM.map<Fatia>((o) => {
      const f = mapa.get(o.id)
      const valor = f?.valor_bruto ?? 0
      return {
        forma: o.id,
        rotulo: o.rotulo,
        valor,
        fechamentos: f?.fechamentos ?? 0,
        pct: total > 0 ? (valor / total) * 100 : 0,
        cor: o.cor,
      }
    })
    const ativas = fatias.filter((f) => f.valor > 0)
    return { fatias, total, ativas }
  }, [itens])

  if (total === 0) {
    return (
      <ChartShell titulo="Mix forma de pagamento">
        <div className="flex h-[180px] items-center justify-center text-sm text-text-muted">
          Sem fechamentos no período.
        </div>
      </ChartShell>
    )
  }

  return (
    <ChartShell
      titulo="Mix forma de pagamento"
      hint={`${ativas.length} forma${ativas.length === 1 ? "" : "s"} registrada${ativas.length === 1 ? "" : "s"}`}
    >
      <div className="flex flex-col gap-3">
        {/* Total como heading próprio — fora da área de hover, sem conflito. */}
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-text-muted">
            Bruto recebido
          </span>
          <span className="font-mono text-[18px] font-semibold tabular-nums text-text-primary">
            {formatBRL(total)}
          </span>
        </div>

        {/* Barra horizontal 100% stacked. Segmentos clicáveis para destacar a
            linha da legenda; legenda destaca a barra. Padrão GitHub/Stripe/
            Linear quando uma fatia domina. */}
        <BarraStacked
          ativas={ativas}
          hover={hover}
          onHover={setHover}
        />

        <ul className="flex flex-col gap-0.5">
          {fatias.map((f) => {
            const inativo = f.valor === 0
            const realcado = hover === f.forma
            return (
              <li
                key={f.forma}
                onMouseEnter={() => !inativo && setHover(f.forma)}
                onMouseLeave={() => setHover(null)}
                className={cn(
                  "grid grid-cols-[10px_1fr_auto_44px] items-baseline gap-2 rounded-sm px-1 py-1 transition-colors",
                  inativo ? "opacity-60" : "cursor-default",
                  realcado && "bg-muted/40",
                )}
              >
                <span
                  aria-hidden
                  className="inline-block size-2 rounded-sm"
                  style={{ background: f.cor, opacity: inativo ? 0.35 : 1 }}
                />
                <span
                  className={cn(
                    "truncate text-[12.5px]",
                    inativo ? "text-text-muted" : "text-text-primary",
                  )}
                >
                  {f.rotulo}
                  {f.fechamentos > 0 && (
                    <span className="ml-1.5 font-mono text-[10.5px] tabular-nums text-text-disabled">
                      · {f.fechamentos} fech.
                    </span>
                  )}
                </span>
                <span
                  className={cn(
                    "text-right font-mono text-[12px] tabular-nums",
                    inativo ? "text-text-disabled" : "text-text-secondary",
                  )}
                >
                  {inativo ? "—" : formatBRL(f.valor)}
                </span>
                <span
                  className={cn(
                    "text-right font-mono text-[12px] font-medium tabular-nums",
                    inativo
                      ? "text-text-disabled"
                      : realcado
                        ? "text-text-primary"
                        : "text-text-secondary",
                  )}
                >
                  {inativo
                    ? "0%"
                    : f.pct < 1
                      ? `${PCT_FINO.format(f.pct)}%`
                      : `${PCT_FMT.format(f.pct)}%`}
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </ChartShell>
  )
}

// ---------- Barra empilhada 100% ----------

function BarraStacked({
  ativas,
  hover,
  onHover,
}: {
  ativas: Fatia[]
  hover: string | null
  onHover: (forma: string | null) => void
}) {
  return (
    <div
      className="flex h-9 w-full overflow-hidden rounded-sm bg-muted/30 ring-1 ring-inset ring-border/50"
      role="group"
      aria-label="Distribuição da receita por forma de pagamento"
    >
      {ativas.map((f, i) => {
        const dim = hover !== null && hover !== f.forma
        return (
          <button
            key={f.forma}
            type="button"
            onMouseEnter={() => onHover(f.forma)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(f.forma)}
            onBlur={() => onHover(null)}
            className={cn(
              "group/seg relative h-full transition-opacity duration-150 focus:outline-none",
              i > 0 && "border-l border-card",
              dim && "opacity-35",
            )}
            style={{ width: `${f.pct}%`, background: f.cor }}
            aria-label={`${f.rotulo}: ${formatBRL(f.valor)} (${PCT_FMT.format(f.pct)}%)`}
            title={`${f.rotulo} — ${formatBRL(f.valor)} (${PCT_FMT.format(f.pct)}%)`}
          >
            {/* Rótulo inline só para fatias ≥ 15% (cabe sem amassar) */}
            {f.pct >= 15 && (
              <span
                className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10.5px] font-semibold uppercase tracking-[0.06em]"
                style={{ color: "var(--on-brand)" }}
              >
                {PCT_FMT.format(f.pct)}%
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
