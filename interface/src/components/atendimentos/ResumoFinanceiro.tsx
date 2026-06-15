"use client"

import { Wallet } from "lucide-react"
import type { EstadoAtendimento, ResumoAtendimentos } from "@/tipos/atendimentos"
import {
  DICA_FATURAMENTO_BRUTO,
  FaixaResumo,
  SkeletonFaixaResumo,
  type ResumoKpi,
} from "@/components/comum/FaixaResumo"
import { TabelaPorModelo } from "@/components/comum/TabelaPorModelo"
import { formatBRL } from "@/lib/formatters"

const ESTADO_LABEL: Record<EstadoAtendimento, string> = {
  Novo: "Novo",
  Triagem: "Triagem",
  Qualificado: "Qualificado",
  Aguardando_confirmacao: "Aguardando",
  Confirmado: "Confirmado",
  Em_execucao: "Em atendimento",
  Fechado: "Fechado",
  Perdido: "Perdido",
}

interface Props {
  resumo: ResumoAtendimentos | null
  status: "loading" | "success" | "error"
}

export function ResumoFinanceiro({ resumo, status }: Props) {
  if (status === "error") return null
  if (!resumo) return <SkeletonFaixaResumo />

  const ticket = resumo.ticket_medio_brl
  const kpis: ResumoKpi[] = [
    {
      label: "Faturamento",
      valor: formatBRL(resumo.faturamento_bruto_brl),
      destaque: true,
      dica: DICA_FATURAMENTO_BRUTO,
    },
    { label: "Fechados", valor: String(resumo.fechados) },
    { label: "Ticket médio", valor: ticket != null ? formatBRL(ticket) : "—" },
    { label: "Atendimentos", valor: String(resumo.total) },
  ]
  const temDetalhe = resumo.por_modelo.length > 0 || resumo.por_estado.length > 0

  return (
    <FaixaResumo rotulo="Resumo" icone={<Wallet size={15} strokeWidth={1.5} aria-hidden />} kpis={kpis}>
      {temDetalhe ? (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_minmax(220px,300px)]">
          <div className="min-w-0">
            <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
              Por modelo
            </h3>
            {resumo.por_modelo.length === 0 ? (
              <p className="text-[13px] text-text-muted">Sem atendimentos no recorte.</p>
            ) : (
              <TabelaPorModelo items={resumo.por_modelo} />
            )}
          </div>

          <div className="min-w-0">
            <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
              Por estado
            </h3>
            <ul className="flex flex-col gap-1">
              {resumo.por_estado.map((e) => (
                <li key={e.estado} className="flex items-center justify-between gap-3 text-[13px]">
                  <span className="text-text-primary">{ESTADO_LABEL[e.estado] ?? e.estado}</span>
                  <span className="flex items-center gap-3 font-mono text-xs tabular-nums">
                    <span className="text-text-muted">{e.total}</span>
                    {e.faturamento_bruto_brl > 0 ? (
                      <span className="text-success-500">{formatBRL(e.faturamento_bruto_brl)}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </FaixaResumo>
  )
}
