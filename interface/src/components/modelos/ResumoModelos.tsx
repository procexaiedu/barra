"use client"

import { Users } from "lucide-react"
import type { ResumoModelos as ResumoModelosData } from "@/tipos/modelos"
import { FaixaResumo, SkeletonFaixaResumo, type ResumoKpi } from "@/components/comum/FaixaResumo"
import { formatBRL } from "@/lib/formatters"

interface Props {
  resumo: ResumoModelosData | null
  status: "loading" | "success" | "error"
}

export function ResumoModelos({ resumo, status }: Props) {
  if (status === "error") return null
  if (!resumo) return <SkeletonFaixaResumo />

  const kpis: ResumoKpi[] = [
    { label: "Modelos", valor: String(resumo.total) },
    { label: "Ativas", valor: String(resumo.ativas) },
    { label: "Inativas", valor: String(resumo.inativas) },
    { label: "Faturamento", valor: formatBRL(resumo.faturamento_bruto_brl), destaque: true },
  ]

  return (
    <FaixaResumo rotulo="Resumo" icone={<Users size={15} strokeWidth={1.5} aria-hidden />} kpis={kpis}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-3 lg:grid-cols-6">
        <Item rotulo="Ativas" valor={resumo.ativas} />
        <Item rotulo="Pausadas" valor={resumo.pausadas} />
        <Item rotulo="Inativas" valor={resumo.inativas} />
        <Item rotulo="WhatsApp pendente" valor={resumo.whatsapp_pendente} />
        <Item rotulo="Sem nível" valor={resumo.sem_nivel} />
        <Item rotulo="Fechados" valor={resumo.fechados} />
      </dl>
    </FaixaResumo>
  )
}

function Item({ rotulo, valor }: { rotulo: string; valor: number }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-text-muted">{rotulo}</dt>
      <dd className="font-mono text-xs text-text-primary tabular-nums">{valor}</dd>
    </div>
  )
}
