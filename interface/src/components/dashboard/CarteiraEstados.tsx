"use client"

import { useRouter } from "next/navigation"
import type { EstadoAtendimento } from "@/tipos/atendimentos"
import type { FunilEstadoLinha } from "@/tipos/dashboard"

interface Props {
  linhas: FunilEstadoLinha[]
}

interface EstadoMeta {
  estado: EstadoAtendimento
  rotulo: string
  cor: string
}

// Ordem reflete o ciclo de vida do atendimento: pipeline → confirmado → execução → desfecho.
const ESTADOS_VISIVEIS: EstadoMeta[] = [
  { estado: "Novo", rotulo: "Novo", cor: "var(--seq-1)" },
  { estado: "Triagem", rotulo: "Triagem", cor: "var(--seq-2)" },
  { estado: "Qualificado", rotulo: "Qualificado", cor: "var(--seq-3)" },
  { estado: "Aguardando_confirmacao", rotulo: "Aguardando", cor: "var(--seq-4)" },
  { estado: "Confirmado", rotulo: "Confirmado", cor: "var(--seq-5)" },
  { estado: "Em_execucao", rotulo: "Em atendimento", cor: "var(--seq-6)" },
  { estado: "Fechado", rotulo: "Fechado", cor: "var(--success-500)" },
  { estado: "Perdido", rotulo: "Perdido", cor: "var(--danger-500)" },
]

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function CarteiraEstados({ linhas }: Props) {
  const router = useRouter()
  const total = linhas.reduce((soma, linha) => soma + linha.contagem, 0)
  const mapa = new Map(linhas.map((l) => [l.estado, l.contagem]))

  const segmentos = ESTADOS_VISIVEIS.map((meta) => {
    const contagem = mapa.get(meta.estado) ?? 0
    return { ...meta, contagem, pct: total > 0 ? (contagem / total) * 100 : 0 }
  }).filter((s) => s.contagem > 0)

  return (
    <section aria-label="Carteira de atendimentos por estado" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Carteira por estado</h2>
        <span className="text-xs font-medium text-text-muted">
          {total} atendimentos no período
        </span>
      </header>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {total === 0 ? (
          <div className="flex flex-col gap-1 rounded-md bg-ink-200 p-4">
            <span className="text-sm text-text-primary">Nenhum atendimento no período selecionado.</span>
            <span className="text-[13px] text-text-muted">Ajuste o período no topo da página.</span>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div
              role="group"
              aria-label="Distribuição dos atendimentos por estado"
              className="flex h-10 w-full overflow-hidden rounded-md ring-1 ring-foreground/10"
            >
              {segmentos.map((s) => (
                <button
                  key={s.estado}
                  type="button"
                  onClick={() => router.push(`/atendimentos?estado=${encodeURIComponent(s.estado)}`)}
                  aria-label={`${s.rotulo}: ${s.contagem} atendimentos (${PCT_FMT.format(s.pct)}%)`}
                  title={`${s.rotulo}: ${s.contagem} (${PCT_FMT.format(s.pct)}%)`}
                  className="group relative flex items-center justify-center transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  style={{ width: `${s.pct}%`, background: s.cor }}
                >
                  <span className="font-mono text-[11px] font-medium tabular-nums text-ink-900/85 opacity-0 transition-opacity group-hover:opacity-100">
                    {s.contagem}
                  </span>
                </button>
              ))}
            </div>

            <ul className="grid grid-cols-2 gap-x-6 gap-y-2 lg:grid-cols-4">
              {segmentos.map((s) => (
                <li key={`legenda-${s.estado}`} className="flex items-center gap-2 text-sm">
                  <span
                    className="inline-block h-2.5 w-2.5 rounded-sm"
                    style={{ background: s.cor }}
                    aria-hidden
                  />
                  <span className="flex-1 text-text-muted">{s.rotulo}</span>
                  <span className="font-mono tabular-nums text-text-primary">{s.contagem}</span>
                  <span className="font-mono text-[11px] tabular-nums text-text-muted">
                    {PCT_FMT.format(s.pct)}%
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
