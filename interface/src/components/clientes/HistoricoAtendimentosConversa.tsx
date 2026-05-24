"use client"

import { useState } from "react"
import type { AtendimentoHistoricoItem } from "@/tipos/clientes"
import { ItemAtendimentoHistorico } from "@/components/clientes/ItemAtendimentoHistorico"
import { ModalVisualizacao } from "@/components/atendimentos/ModalVisualizacao"

const ITENS_POR_PAGINA = 5

export function HistoricoAtendimentosConversa({
  itens,
}: {
  itens: AtendimentoHistoricoItem[]
}) {
  const [atendimentoSelecionado, setAtendimentoSelecionado] = useState<string | null>(null)
  const [pagina, setPagina] = useState(1)

  const exibidos = itens.slice(0, pagina * ITENS_POR_PAGINA)
  const restante = itens.length - exibidos.length

  return (
    <>
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
          <div className="-mx-5">
            <div className="divide-y divide-border">
              {exibidos.map((item) => (
                <ItemAtendimentoHistorico
                  key={item.id}
                  item={item}
                  onClick={() => setAtendimentoSelecionado(item.id)}
                />
              ))}
            </div>
            {restante > 0 && (
              <button
                type="button"
                onClick={() => setPagina((p) => p + 1)}
                className="w-full py-2.5 text-center text-xs font-medium text-text-secondary
                           hover:text-text-primary hover:bg-surface-hover
                           border-t border-border transition-colors"
              >
                Ver mais {restante} atendimentos
              </button>
            )}
          </div>
        )}
      </section>

      <ModalVisualizacao
        atendimentoId={atendimentoSelecionado}
        onClose={() => setAtendimentoSelecionado(null)}
        readOnly
      />
    </>
  )
}
