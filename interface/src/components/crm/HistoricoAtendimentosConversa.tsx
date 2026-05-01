"use client"

import type { AtendimentoHistoricoItem } from "@/tipos/crm"
import { ItemAtendimentoHistorico } from "@/components/crm/ItemAtendimentoHistorico"

export function HistoricoAtendimentosConversa({
  itens,
}: {
  itens: AtendimentoHistoricoItem[]
}) {
  return (
    <section
      aria-label="Histórico de atendimentos da conversa"
      className="rounded-lg border border-border bg-card p-6"
    >
      <h2 className="mb-4 text-base font-semibold text-text-primary">Histórico</h2>
      {itens.length === 0 ? (
        <p className="text-[13px] text-text-muted">
          Nenhum atendimento registrado ainda nesta conversa.
        </p>
      ) : (
        <div className="-mx-6 divide-y divide-border">
          {itens.map((item) => (
            <ItemAtendimentoHistorico key={item.id} item={item} />
          ))}
        </div>
      )}
    </section>
  )
}
