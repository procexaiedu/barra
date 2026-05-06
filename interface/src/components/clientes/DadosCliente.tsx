"use client"

import { formatBRL } from "@/lib/formatters"
import type { ClienteDetalhe, AtendimentoHistoricoItem } from "@/tipos/clientes"

export function DadosCliente({
  cliente,
  historico,
}: {
  cliente: ClienteDetalhe
  historico: AtendimentoHistoricoItem[]
}) {
  const fechados = historico.filter((h) => h.estado === "Fechado")
  const perdidos = historico.filter((h) => h.estado === "Perdido")
  const receita = fechados.reduce((acc, curr) => acc + (Number(curr.valor_final) || 0), 0)
  const ticketMedio = fechados.length > 0 ? receita / fechados.length : 0

  return (
    <div
      aria-label="Métricas do cliente"
      className="grid grid-cols-4 divide-x divide-border rounded-lg border border-border bg-card"
    >
      <Metrica label="Fechados">
        <span className="text-2xl font-semibold text-text-primary">
          {fechados.length > 0 ? fechados.length : "—"}
        </span>
      </Metrica>
      <Metrica label="Perdidos">
        <span className={`text-2xl font-semibold ${perdidos.length > 0 ? "text-state-lost" : "text-text-primary"}`}>
          {perdidos.length > 0 ? perdidos.length : "—"}
        </span>
      </Metrica>
      <Metrica label="Receita Total">
        <span className={`text-lg font-semibold ${receita > 0 ? "text-state-closed" : "text-text-primary"}`}>
          {receita > 0 ? formatBRL(receita) : "—"}
        </span>
      </Metrica>
      <Metrica label="Ticket Médio">
        <span className="text-lg font-semibold text-text-primary">
          {ticketMedio > 0 ? formatBRL(ticketMedio) : "—"}
        </span>
      </Metrica>
    </div>
  )
}

function Metrica({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
      </span>
      {children}
    </div>
  )
}
