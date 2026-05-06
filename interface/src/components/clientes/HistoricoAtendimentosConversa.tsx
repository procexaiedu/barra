"use client"

import type { AtendimentoHistoricoItem } from "@/tipos/clientes"
import { ItemAtendimentoHistorico } from "@/components/clientes/ItemAtendimentoHistorico"

export function HistoricoAtendimentosConversa({
  itens,
}: {
  itens: AtendimentoHistoricoItem[]
}) {
  return (
    <section
      aria-label="Histórico de atendimentos da conversa"
      className="rounded-lg border border-border bg-card p-5"
    >
      <p className="mb-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        Histórico
      </p>
      {itens.length === 0 ? (
        <p className="text-[13px] text-text-muted">
          Nenhum atendimento registrado ainda nesta conversa.
        </p>
      ) : (
        <div className="-mx-5 divide-y divide-border">
          {itens.map((item) => (
            <ItemAtendimentoHistorico key={item.id} item={item} />
          ))}
        </div>
      )}
    </section>
  )
}
