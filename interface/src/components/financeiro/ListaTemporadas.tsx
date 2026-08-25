"use client"

import Link from "next/link"
import { AlertTriangle, ArrowUpRight, MapPin } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { EstadoDaTemporada, TemporadaLinha, TemporadasListaResponse } from "@/tipos/razao"
import { FaltaPagar, SaldoComSinal } from "./SaldoComSinal"

const ESTADO: Record<EstadoDaTemporada, { rotulo: string; classe: string }> = {
  aberta: { rotulo: "Aberta", classe: "border-state-active/30 bg-state-active/15 text-state-active" },
  fechada: { rotulo: "Fechada", classe: "border-state-closed/30 bg-state-closed/15 text-state-closed" },
  cancelada: { rotulo: "Cancelada", classe: "border-border bg-muted/50 text-text-muted" },
}

/**
 * As temporadas com modelo, cidade, período e o saldo com sinal — o "financeiro dos
 * telefonistas" num lugar só, sem o gestor entrar em grupo nenhum.
 *
 * Cada linha leva ao extrato daquela modelo JÁ RECORTADO pela temporada, porque a pergunta que
 * vem depois de "quanto devo a ela" é sempre "por quê".
 */
export function ListaTemporadas({
  lista,
  loading,
  error,
  onRetry,
}: {
  lista: TemporadasListaResponse | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  if (loading && !lista) return <Skeleton className="h-[240px] w-full rounded-lg" />

  if (error && !lista) {
    return (
      <div className="rounded-lg border border-danger-500/40 bg-[color:var(--danger-500)]/8 px-4 py-3">
        <p className="text-[13px] text-text-primary">{error}</p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-[12px] font-medium text-text-brand underline underline-offset-2"
        >
          Tentar de novo
        </button>
      </div>
    )
  }

  if (!lista || lista.items.length === 0) {
    return (
      <div className="rounded-lg bg-card px-4 py-10 text-center ring-1 ring-border-subtle">
        <p className="text-[13px] text-text-primary">Nenhuma temporada neste filtro.</p>
        <p className="mt-1 text-[12px] text-text-muted">
          A temporada é a viagem da modelo para uma cidade, e é a unidade de pagamento do negócio.
          Fechar uma é ação do painel, nunca frase solta no grupo.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-text-muted">
        <span>
          A casa deve{" "}
          <span className="font-mono tabular-nums text-success-500">
            {formatBRL(lista.total_a_casa_deve_brl)}
          </span>
        </span>
        <span>
          Elas devem{" "}
          <span className="font-mono tabular-nums text-warn-500">
            {formatBRL(lista.total_ela_deve_brl)}
          </span>
        </span>
        <span>
          Falta pagar{" "}
          <span className="font-mono tabular-nums text-text-primary">
            {formatBRL(lista.total_falta_pagar_brl)}
          </span>
        </span>
      </div>

      <ul
        aria-label="Temporadas"
        className="overflow-hidden rounded-lg bg-card ring-1 ring-border-subtle shadow-elev-1"
      >
        {lista.items.map((t) => (
          <LinhaTemporada key={t.id} temporada={t} />
        ))}
      </ul>
    </div>
  )
}

function LinhaTemporada({ temporada: t }: { temporada: TemporadaLinha }) {
  const estado = ESTADO[t.estado]
  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        href={`/modelos/${t.modelo_id}?temporada_id=${t.id}`}
        className="grid grid-cols-1 items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:grid-cols-[minmax(0,1.4fr)_auto_auto_auto_auto]"
      >
        <div className="min-w-0">
          <span className="flex items-center gap-2">
            <span className="truncate text-[14px] font-medium text-text-primary">
              {t.modelo_nome}
            </span>
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium",
                estado.classe,
              )}
            >
              {estado.rotulo}
            </span>
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-text-muted">
            <span className="flex items-center gap-1">
              <MapPin className="size-3" aria-hidden />
              {t.cidade}
            </span>
            <span className="font-mono tabular-nums">
              {formatData(t.data_inicio)} → {formatData(t.data_fim)}
            </span>
          </span>
        </div>

        <div className="flex flex-col gap-0.5 md:text-right">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            Vendido
          </span>
          <span className="font-mono text-base font-semibold tabular-nums leading-none text-text-primary">
            {formatBRL(t.vendido_brl)}
          </span>
          <span className="font-mono text-[10.5px] tabular-nums text-text-muted">
            {t.vendas} {t.vendas === 1 ? "venda" : "vendas"}
          </span>
        </div>

        <SaldoComSinal saldo={t.saldo} tamanho="sm" nome={t.modelo_nome} />
        <FaltaPagar saldo={t.saldo} />

        <span className="flex items-center gap-3 md:justify-end">
          {t.pendencias > 0 && (
            <span className="inline-flex items-center gap-1 rounded-sm bg-[color:var(--warn-500)]/12 px-1.5 py-0.5 text-[10.5px] font-medium tabular-nums text-warn-500">
              <AlertTriangle className="size-3" aria-hidden />
              {t.pendencias}
            </span>
          )}
          <ArrowUpRight className="size-4 shrink-0 text-text-muted" aria-hidden />
        </span>
      </Link>
    </li>
  )
}
