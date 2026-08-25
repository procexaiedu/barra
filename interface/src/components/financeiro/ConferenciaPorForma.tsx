"use client"

import { Banknote, CreditCard, Landmark, Link2, QrCode, HelpCircle } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { ConferenciaPorFormaResponse } from "@/tipos/razao"
import { ROTULO_DA_FORMA } from "@/tipos/razao"

const ICONE: Record<string, typeof Banknote> = {
  pix: QrCode,
  dinheiro: Banknote,
  debito: Landmark,
  credito: CreditCard,
  link: Link2,
  sem_forma: HelpCircle,
}

/**
 * A conferência por forma de pagamento: pix, dinheiro, débito, crédito e link (ADR-0046 §4 —
 * "cartão" deixou de ser uma forma só), mais `sem_forma`.
 *
 * A coluna zerada NÃO é escondida: uma conferência que some com a forma vazia obriga o gestor a
 * lembrar do que faltou. E `sem_forma` aparece com o mesmo peso das outras — é a fila da cobrança
 * consolidada da manhã, e ela é o motivo de o vendido do painel bater ou não com o do grupo.
 */
export function ConferenciaPorForma({
  conferencia,
  loading,
}: {
  conferencia: ConferenciaPorFormaResponse | null
  loading: boolean
}) {
  if (loading && !conferencia) {
    return <Skeleton className="h-[120px] w-full rounded-lg" />
  }
  if (!conferencia) return null

  return (
    <section
      aria-label="Conferência por forma de pagamento"
      className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-border-subtle shadow-elev-1"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-text-primary">
          Conferência por forma
        </h2>
        <span className="text-[11px] text-text-muted">
          {conferencia.de && conferencia.ate
            ? `${formatData(conferencia.de)} → ${formatData(conferencia.ate)}`
            : "saldo corrente"}
          <span className="mx-1.5">·</span>
          <span className="font-mono tabular-nums text-text-primary">
            {formatBRL(conferencia.vendido_brl)}
          </span>
          <span className="ml-1">
            em {conferencia.vendas} {conferencia.vendas === 1 ? "venda" : "vendas"}
          </span>
        </span>
      </div>

      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {conferencia.formas.map((f) => {
          const Icone = ICONE[f.forma] ?? HelpCircle
          const vazia = f.vendas === 0
          const pendente = f.forma === "sem_forma" && f.vendas > 0
          return (
            <li
              key={f.forma}
              className={cn(
                "flex flex-col gap-1 rounded-md border px-3 py-2",
                pendente
                  ? "border-warn-500/40 bg-[color:var(--warn-500)]/8"
                  : "border-border-subtle bg-muted/25",
                vazia && "opacity-55",
              )}
            >
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-text-muted">
                <Icone className="size-3.5" aria-hidden />
                {ROTULO_DA_FORMA[f.forma] ?? f.forma}
              </span>
              <span
                className={cn(
                  "font-mono text-[15px] font-semibold tabular-nums leading-none",
                  pendente ? "text-warn-500" : "text-text-primary",
                )}
              >
                {formatBRL(f.valor_brl)}
              </span>
              <span className="font-mono text-[10.5px] tabular-nums text-text-muted">
                {f.vendas} {f.vendas === 1 ? "venda" : "vendas"}
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
