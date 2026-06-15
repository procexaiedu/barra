"use client"

import { Wallet } from "lucide-react"
import type { ResumoClientes as ResumoClientesData } from "@/tipos/clientes"
import { FaixaResumo, SkeletonFaixaResumo, type ResumoKpi } from "@/components/comum/FaixaResumo"
import { TabelaPorModelo } from "@/components/comum/TabelaPorModelo"
import { formatBRL } from "@/lib/formatters"

interface Props {
  resumo: ResumoClientesData | null
  status: "loading" | "success" | "error"
}

export function ResumoClientes({ resumo, status }: Props) {
  if (status === "error") return null
  if (!resumo) return <SkeletonFaixaResumo />

  const ticket = resumo.ticket_medio_brl
  const kpis: ResumoKpi[] = [
    { label: "Faturamento", valor: formatBRL(resumo.faturamento_bruto_brl), destaque: true },
    { label: "Clientes", valor: String(resumo.total_clientes) },
    { label: "Recorrentes", valor: String(resumo.recorrentes) },
    { label: "Ticket médio", valor: ticket != null ? formatBRL(ticket) : "—" },
  ]

  return (
    <FaixaResumo rotulo="Resumo" icone={<Wallet size={15} strokeWidth={1.5} aria-hidden />} kpis={kpis}>
      {resumo.por_modelo.length > 0 ? (
        <div className="min-w-0">
          <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            Faturamento por modelo
          </h3>
          <TabelaPorModelo items={resumo.por_modelo} />
        </div>
      ) : (
        <p className="text-[13px] text-text-muted">Sem fechamentos no recorte.</p>
      )}
    </FaixaResumo>
  )
}
