"use client"

import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import type { ReceitasListaResponse } from "@/tipos/financeiro"

export function ListaReceitas({
  lista,
  loading,
}: {
  lista: ReceitasListaResponse | null
  loading: boolean
}) {
  if (loading && !lista) return <Skeleton className="h-64" />
  if (!lista || lista.items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-text-muted">
        Nenhuma receita no período.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
            <th className="px-3 py-2 text-left">Data</th>
            <th className="px-3 py-2 text-left">#</th>
            <th className="px-3 py-2 text-left">Modelo</th>
            <th className="px-3 py-2 text-left">Cliente</th>
            <th className="px-3 py-2 text-left">Forma</th>
            <th className="px-3 py-2 text-right">Bruto</th>
            <th className="px-3 py-2 text-right">%</th>
            <th className="px-3 py-2 text-right">Repasse calc.</th>
          </tr>
        </thead>
        <tbody>
          {lista.items.map((r) => (
            <tr key={r.atendimento_id} className="border-b border-border/60 hover:bg-muted/20">
              <td className="px-3 py-2 text-text-muted">{formatData(r.fechado_em)}</td>
              <td className="px-3 py-2 font-mono text-xs">#{r.numero_curto}</td>
              <td className="px-3 py-2">{r.modelo_nome}</td>
              <td className="px-3 py-2">{r.cliente_nome}</td>
              <td className="px-3 py-2 text-text-muted">{r.forma_pagamento ?? "—"}</td>
              <td className="px-3 py-2 text-right tabular-nums">{formatBRL(r.valor_bruto)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-text-muted">
                {r.percentual_repasse_snapshot !== null
                  ? `${r.percentual_repasse_snapshot.toFixed(0)}%`
                  : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {formatBRL(r.valor_repasse_calculado)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {lista.next_cursor && (
        <div className="border-t border-border bg-muted/10 px-3 py-2 text-center text-xs text-text-muted">
          Mais resultados disponíveis — refine o período ou modelo para ver tudo.
        </div>
      )}
    </div>
  )
}
