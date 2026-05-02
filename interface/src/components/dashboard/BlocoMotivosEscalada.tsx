"use client"

import { useRouter } from "next/navigation"
import type { MotivosEscalada } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"

interface Props {
  data: MotivosEscalada
  onAbrirTodas: () => void
}

export function BlocoMotivosEscalada({ data, onAbrirTodas }: Props) {
  const router = useRouter()
  const navegarParaMotivo = (motivo: string) =>
    router.push(
      `/atendimentos?ia_pausada=true&motivo_escalada=${encodeURIComponent(motivo)}`
    )

  const maximo = Math.max(...data.top5.map((l) => l.contagem), 0)

  return (
    <section
      aria-label="Motivos de escalada"
      className="flex flex-col gap-3"
    >
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Motivos de escalada</h2>
        <span className="text-xs font-medium text-text-muted">{data.total} no período</span>
      </header>
      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {data.total === 0 ? (
          <p className="text-sm text-text-muted">Sem atendimentos escalados no período.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {data.top5.map((linha) => {
              const pctLargura = maximo > 0 ? (linha.contagem / maximo) * 100 : 0
              return (
                <li key={linha.motivo}>
                  <button
                    type="button"
                    onClick={() => navegarParaMotivo(linha.motivo)}
                    className={cn(
                      "grid h-8 w-full grid-cols-[1fr_140px_36px] items-center gap-3 rounded-md px-1 text-left",
                      "transition-colors hover:bg-ink-200",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    )}
                    aria-label={`${linha.motivo}: ${linha.contagem} escalas`}
                  >
                    <span className="truncate text-[13px] text-text-primary" title={linha.motivo}>
                      {linha.motivo}
                    </span>
                    <span
                      role="progressbar"
                      aria-valuenow={linha.contagem}
                      aria-valuemin={0}
                      aria-valuemax={maximo > 0 ? maximo : 1}
                      className="relative block h-3 w-full"
                    >
                      <span
                        aria-hidden
                        className="absolute left-0 right-0 top-1/2 block h-px -translate-y-1/2 bg-ink-300"
                      />
                      <span
                        aria-hidden
                        className="absolute left-0 top-1/2 block h-px -translate-y-1/2 bg-warn-500 transition-[width]"
                        style={{ width: `${pctLargura}%` }}
                      />
                      <span
                        aria-hidden
                        className="absolute top-1/2 block h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-warn-500 ring-2 ring-card transition-[left]"
                        style={{ left: `${pctLargura}%` }}
                      />
                    </span>
                    <span className="text-right font-mono text-xs font-medium text-text-primary tabular-nums">
                      {linha.contagem}
                    </span>
                  </button>
                </li>
              )
            })}
            {data.outros_total > 0 ? (
              <li>
                <button
                  type="button"
                  onClick={onAbrirTodas}
                  className={cn(
                    "grid h-8 w-full grid-cols-[1fr_140px_36px] items-center gap-3 rounded-md px-1 text-left",
                    "transition-colors hover:bg-ink-200",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  )}
                  aria-label={`Outros ${data.outros_total}`}
                >
                  <span className="truncate text-[13px] text-text-muted">
                    Outros ({data.outros_total})
                  </span>
                  <span aria-hidden className="block h-3 w-full" />
                  <span className="text-right font-mono text-xs font-medium text-text-muted tabular-nums">
                    {data.outros_total}
                  </span>
                </button>
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </section>
  )
}
