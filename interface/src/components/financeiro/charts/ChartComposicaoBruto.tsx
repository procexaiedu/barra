"use client"

import { useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import type { FinanceiroResumo } from "@/tipos/financeiro"
import { ChartShell } from "./ChartReceitaDiaria"

interface Props {
  resumo: FinanceiroResumo
}

type SegId = "liquido" | "pago" | "saldo" | "estorno"

interface Seg {
  id: SegId
  rotulo: string
  valor: number
  pct: number
  cor: string
  descricao: string
}

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const PCT_FINO = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

// Decompõe o bruto em fatias mutuamente exclusivas que somam 100% da receita:
//   Líquido (Elite Baby)  +  Repasse pago  +  Saldo a pagar  =  Bruto
// Quando há estorno (pago > calculado), o excedente vira fatia em vermelho
// que canibaliza visualmente o pago — a soma continua = bruto.
export function ChartComposicaoBruto({ resumo }: Props) {
  const [hover, setHover] = useState<SegId | null>(null)

  const { segs, ativas, total } = useMemo(() => {
    const bruto = resumo.valor_bruto_brl
    const liquido = resumo.valor_liquido_brl
    const pagoOriginal = resumo.valor_repasse_pago_brl
    const saldo = resumo.valor_saldo_repasse_brl
    const temEstorno = saldo < -0.005
    const estorno = temEstorno ? Math.abs(saldo) : 0
    const pago = temEstorno ? pagoOriginal - estorno : pagoOriginal
    const saldoPos = temEstorno ? 0 : Math.max(0, saldo)

    const lista: Seg[] = [
      {
        id: "liquido",
        rotulo: "Líquido Elite Baby",
        valor: liquido,
        pct: bruto > 0 ? (liquido / bruto) * 100 : 0,
        cor: "var(--gold-500)",
        descricao: "fica com a Elite Baby",
      },
      {
        id: "pago",
        rotulo: "Repasse pago",
        valor: pago,
        pct: bruto > 0 ? (pago / bruto) * 100 : 0,
        cor: "var(--success-500)",
        descricao: "já saiu pra modelo",
      },
      {
        id: "saldo",
        rotulo: "Saldo a pagar",
        valor: saldoPos,
        pct: bruto > 0 ? (saldoPos / bruto) * 100 : 0,
        cor: "var(--warn-500)",
        descricao: "ainda devido às modelos",
      },
    ]
    if (temEstorno) {
      lista.push({
        id: "estorno",
        rotulo: "Pago a mais",
        valor: estorno,
        pct: bruto > 0 ? (estorno / bruto) * 100 : 0,
        cor: "var(--danger-500)",
        descricao: "estorno pendente",
      })
    }
    return { segs: lista, ativas: lista.filter((s) => s.valor > 0.005), total: bruto }
  }, [resumo])

  if (total === 0) {
    return (
      <ChartShell titulo="Composição do bruto">
        <div className="flex h-[120px] items-center justify-center text-sm text-text-muted">
          Sem fechamentos no período.
        </div>
      </ChartShell>
    )
  }

  return (
    <ChartShell
      titulo="Composição do bruto"
      hint="líquido + repasses = bruto"
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.1em] text-text-muted">
            Bruto recebido
          </span>
          <span className="font-mono text-[18px] font-semibold tabular-nums text-aurum">
            {formatBRL(total)}
          </span>
        </div>

        <BarraStacked ativas={ativas} hover={hover} onHover={setHover} />

        <ul className="grid grid-cols-1 gap-0.5 sm:grid-cols-2 lg:grid-cols-4">
          {segs.map((s) => {
            const inativo = s.valor < 0.005
            const realcado = hover === s.id
            return (
              <li
                key={s.id}
                onMouseEnter={() => !inativo && setHover(s.id)}
                onMouseLeave={() => setHover(null)}
                className={cn(
                  "grid grid-cols-[10px_1fr_auto] items-baseline gap-2 rounded-sm px-1 py-1 transition-colors",
                  inativo ? "opacity-60" : "cursor-default",
                  realcado && "bg-muted/40",
                )}
              >
                <span
                  aria-hidden
                  className="inline-block size-2 rounded-sm"
                  style={{ background: s.cor, opacity: inativo ? 0.35 : 1 }}
                />
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block truncate text-[12.5px]",
                      inativo ? "text-text-muted" : "text-text-primary",
                    )}
                  >
                    {s.rotulo}
                  </span>
                  <span className="block truncate text-[10.5px] text-text-disabled">
                    {inativo ? "—" : s.descricao}
                  </span>
                </span>
                <span className="flex flex-col items-end gap-0">
                  <span
                    className={cn(
                      "text-right font-mono text-[12px] tabular-nums",
                      inativo ? "text-text-disabled" : "text-text-secondary",
                    )}
                  >
                    {inativo ? "—" : formatBRL(s.valor)}
                  </span>
                  <span
                    className={cn(
                      "text-right font-mono text-[10.5px] font-medium tabular-nums",
                      inativo
                        ? "text-text-disabled"
                        : realcado
                          ? "text-text-primary"
                          : "text-text-muted",
                    )}
                  >
                    {inativo
                      ? "0%"
                      : s.pct < 1
                        ? `${PCT_FINO.format(s.pct)}%`
                        : `${PCT_FMT.format(s.pct)}%`}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      </div>
    </ChartShell>
  )
}

function BarraStacked({
  ativas,
  hover,
  onHover,
}: {
  ativas: Seg[]
  hover: SegId | null
  onHover: (id: SegId | null) => void
}) {
  return (
    <div
      className="flex h-9 w-full overflow-hidden rounded-sm bg-muted/30 ring-1 ring-inset ring-border/50"
      role="group"
      aria-label="Composição do faturamento bruto"
    >
      {ativas.map((s, i) => {
        const dim = hover !== null && hover !== s.id
        return (
          <button
            key={s.id}
            type="button"
            onMouseEnter={() => onHover(s.id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(s.id)}
            onBlur={() => onHover(null)}
            className={cn(
              "group/seg relative h-full transition-opacity duration-150 focus:outline-none",
              i > 0 && "border-l border-card",
              dim && "opacity-35",
            )}
            style={{ width: `${s.pct}%`, background: s.cor }}
            aria-label={`${s.rotulo}: ${formatBRL(s.valor)} (${PCT_FMT.format(s.pct)}%)`}
            title={`${s.rotulo} — ${formatBRL(s.valor)} (${PCT_FMT.format(s.pct)}%)`}
          >
            {s.pct >= 12 && (
              <span
                className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10.5px] font-semibold uppercase tracking-[0.06em]"
                style={{ color: "var(--on-brand)" }}
              >
                {PCT_FMT.format(s.pct)}%
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
