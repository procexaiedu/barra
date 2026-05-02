"use client"

import { formatData, formatTelefone, formatBRL } from "@/lib/formatters"
import type { ClienteDetalhe, AtendimentoHistoricoItem } from "@/tipos/crm"

export function DadosCliente({
  cliente,
  historico,
}: {
  cliente: ClienteDetalhe
  historico: AtendimentoHistoricoItem[]
}) {
  const fechados = historico.filter((h) => h.estado === "Fechado")
  const perdidos = historico.filter((h) => h.estado === "Perdido")
  const receita = fechados.reduce((acc, curr) => acc + (curr.valor_final || 0), 0)
  const ticketMedio = fechados.length > 0 ? receita / fechados.length : 0

  return (
    <section
      aria-label="Dados do cliente"
      className="rounded-lg border border-border bg-card p-4"
    >
      <h2 className="mb-3 text-sm font-semibold text-text-primary">Dados do cliente</h2>
      <dl className="space-y-4">
        <Linha rotulo="Telefone">
          <span className="font-mono text-xs text-text-muted">
            {formatTelefone(cliente.telefone)}
          </span>
        </Linha>

        <Linha rotulo="Nome">
          <span className="text-sm text-text-primary">
            {cliente.nome || "Não informado"}
          </span>
        </Linha>

        <Linha rotulo="Primeiro contato">
          <span className="text-sm text-text-primary">
            {cliente.primeiro_contato_modelo_nome ?? "Não informado"}
          </span>
        </Linha>

        <Linha rotulo="Cliente desde">
          <span className="text-sm text-text-primary">{formatData(cliente.created_at)}</span>
        </Linha>

        <div className="pt-2 mt-2 border-t border-border">
          <h3 className="mb-3 text-[13px] font-medium text-text-muted">Estatísticas do Cliente</h3>
          <div className="space-y-2">
            <Linha rotulo="Atendimentos Fechados">
              <span className="text-sm font-medium text-text-primary">{fechados.length}</span>
            </Linha>
            <Linha rotulo="Atendimentos Perdidos">
              <span className="text-sm text-text-primary">{perdidos.length}</span>
            </Linha>
            {fechados.length > 0 && (
              <>
                <Linha rotulo="Receita Total">
                  <span className="text-sm font-medium text-state-won">
                    {formatBRL(receita)}
                  </span>
                </Linha>
                <Linha rotulo="Ticket Médio">
                  <span className="text-sm text-text-primary">
                    {formatBRL(ticketMedio)}
                  </span>
                </Linha>
              </>
            )}
          </div>
        </div>
      </dl>
    </section>
  )
}

function Linha({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <dt className="min-w-[140px] text-xs font-medium text-text-muted">{rotulo}</dt>
      <dd>{children}</dd>
    </div>
  )
}
