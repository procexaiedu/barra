"use client"

import { useRouter } from "next/navigation"
import type { EstadoAtendimento } from "@/tipos/atendimentos"
import type { FunilEstadoLinha } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"

interface Props {
  linhas: FunilEstadoLinha[]
}

interface EtapaFunil {
  id: string // bate com o param ?estado= aceito por /atendimentos
  rotulo: string
  estados: EstadoAtendimento[]
  cor: string
  desfecho: boolean // Fechado e Perdido — mostram % dos decididos, não conversão entre etapas
}

// 5 etapas espelhando KanbanBoard.tsx (COLUNAS_ATIVAS + COLUNAS_TERMINAIS).
const ETAPAS_FUNIL: EtapaFunil[] = [
  {
    id: "Qualificando",
    rotulo: "Qualificando",
    estados: ["Novo", "Triagem", "Qualificado"],
    cor: "var(--seq-2)",
    desfecho: false,
  },
  {
    id: "Aguardando",
    rotulo: "Aguardando",
    estados: ["Aguardando_confirmacao", "Confirmado"],
    cor: "var(--seq-4)",
    desfecho: false,
  },
  {
    id: "Em_execucao",
    rotulo: "Em atendimento",
    estados: ["Em_execucao"],
    cor: "var(--seq-6)",
    desfecho: false,
  },
  {
    id: "Fechado",
    rotulo: "Fechado",
    estados: ["Fechado"],
    cor: "var(--success-500)",
    desfecho: true,
  },
  {
    id: "Perdido",
    rotulo: "Perdido",
    estados: ["Perdido"],
    cor: "var(--danger-500)",
    desfecho: true,
  },
]

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function CarteiraEstados({ linhas }: Props) {
  const router = useRouter()
  const mapa = new Map(linhas.map((l) => [l.estado, l.contagem]))

  const etapas = ETAPAS_FUNIL.map((meta) => ({
    ...meta,
    contagem: meta.estados.reduce((soma, est) => soma + (mapa.get(est) ?? 0), 0),
  }))

  const total = etapas.reduce((soma, e) => soma + e.contagem, 0)
  const maior = Math.max(...etapas.map((e) => e.contagem), 1)
  const decididos =
    (etapas.find((e) => e.id === "Fechado")?.contagem ?? 0) +
    (etapas.find((e) => e.id === "Perdido")?.contagem ?? 0)

  return (
    <section aria-label="Funil de atendimentos por etapa" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Funil por etapa</h2>
        <span className="text-xs font-medium text-text-muted">
          {total} atendimentos no período
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {total === 0 ? (
          <div className="flex flex-col gap-1 rounded-md bg-muted p-4">
            <span className="text-sm text-text-primary">Nenhum atendimento no período selecionado.</span>
            <span className="text-[13px] text-text-muted">Ajuste o período no topo da página.</span>
          </div>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {etapas.map((etapa) => {
              const pctMax = (etapa.contagem / maior) * 100
              const pctTotal = total > 0 ? (etapa.contagem / total) * 100 : 0
              const pctDecididos =
                etapa.desfecho && decididos > 0 ? (etapa.contagem / decididos) * 100 : null
              const inativo = etapa.contagem === 0
              const handleClick = inativo
                ? undefined
                : () => router.push(`/atendimentos?estado=${encodeURIComponent(etapa.id)}`)
              return (
                <li key={etapa.id}>
                  <button
                    type="button"
                    onClick={handleClick}
                    disabled={inativo}
                    className={cn(
                      "grid w-full grid-cols-[140px_1fr_56px_72px] items-center gap-3 rounded-md py-1.5 pl-2 pr-3 text-left",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      inativo ? "opacity-50" : "transition-colors hover:bg-accent"
                    )}
                    aria-label={`${etapa.rotulo}: ${etapa.contagem} atendimentos`}
                  >
                    <span
                      className={cn(
                        "truncate text-[13px]",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {etapa.rotulo}
                    </span>
                    <div className="relative h-3 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full transition-[width] duration-300"
                        style={{ width: `${pctMax}%`, background: etapa.cor }}
                      />
                    </div>
                    <span
                      className={cn(
                        "text-right font-mono text-xs font-medium tabular-nums",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {etapa.contagem}
                    </span>
                    <span
                      className="text-right text-xs font-medium text-text-muted tabular-nums"
                      title={
                        pctDecididos !== null
                          ? `${PCT_FMT.format(pctDecididos)}% dos decididos (${decididos})`
                          : `${PCT_FMT.format(pctTotal)}% do total`
                      }
                    >
                      {pctDecididos !== null
                        ? `${PCT_FMT.format(pctDecididos)}% dec.`
                        : `${PCT_FMT.format(pctTotal)}%`}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
