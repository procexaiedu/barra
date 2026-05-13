"use client"

import { useMemo } from "react"
import { useRouter } from "next/navigation"
import type { BreakdownModelo, MotivoEscaladaPorTipo, MotivosEscalada } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"
import { rotuloTipoEscalada } from "./utils"
import type { TipoEscalada } from "@/tipos/dashboard"

interface Props {
  data: MotivosEscalada
  onAbrirTodas: () => void
}

const TIPOS_CANONICOS: TipoEscalada[] = [
  "pix_validado",
  "pix_duvidoso",
  "foto_portaria",
  "aviso_saida",
  "fora_de_oferta",
  "comportamento_atipico",
  "indisponibilidade",
  "outro",
]

// Paleta sequencial para o stacking por modelo — até 6 modelos cobertos visualmente.
const CORES_MODELO = [
  "var(--seq-1)",
  "var(--seq-2)",
  "var(--seq-3)",
  "var(--seq-4)",
  "var(--seq-5)",
  "var(--seq-6)",
]

function montarMapaCores(linhas: MotivoEscaladaPorTipo[]): Map<string, string> {
  const totais = new Map<string, number>()
  for (const linha of linhas) {
    for (const seg of linha.por_modelo) {
      totais.set(seg.modelo_id, (totais.get(seg.modelo_id) ?? 0) + seg.contagem)
    }
  }
  const ordenados = Array.from(totais.entries()).sort((a, b) => b[1] - a[1])
  return new Map(
    ordenados.map(([id], idx) => [id, CORES_MODELO[idx % CORES_MODELO.length]])
  )
}

export function BlocoMotivosEscalada({ data, onAbrirTodas }: Props) {
  const router = useRouter()

  const linhas = useMemo<MotivoEscaladaPorTipo[]>(() => {
    if (data.por_tipo && data.por_tipo.length > 0) {
      const mapa = new Map(data.por_tipo.map((l) => [l.tipo, l]))
      return TIPOS_CANONICOS.map((tipo) => {
        const existente = mapa.get(tipo)
        if (existente) return existente
        return {
          tipo,
          rotulo: rotuloTipoEscalada(tipo),
          contagem: 0,
          por_modelo: [],
        }
      }).sort((a, b) => b.contagem - a.contagem)
    }
    // Fallback: backend antigo só devolve top5 com string livre.
    return data.top5.map((l) => ({
      tipo: (l.tipo ?? "outro") as TipoEscalada,
      rotulo: l.motivo,
      contagem: l.contagem,
      por_modelo: [] as BreakdownModelo[],
    }))
  }, [data])

  const maximo = Math.max(...linhas.map((l) => l.contagem), 1)
  const mapaCores = useMemo(() => montarMapaCores(linhas), [linhas])

  const navegarParaTipo = (tipo: TipoEscalada) =>
    router.push(`/atendimentos?ia_pausada=true&tipo_escalada=${encodeURIComponent(tipo)}`)

  return (
    <section aria-label="Motivos de escalada" className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Motivos de escalada</h2>
        <span className="text-xs font-medium text-text-muted">{data.total} no período</span>
      </header>
      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        {data.total === 0 ? (
          <p className="text-sm text-text-muted">Sem atendimentos escalados no período.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {linhas.map((linha) => {
              const pctBarra = (linha.contagem / maximo) * 100
              const inativo = linha.contagem === 0
              const segmentos = linha.por_modelo.length > 0
                ? linha.por_modelo
                : linha.contagem > 0
                  ? [{ modelo_id: "_agregado", nome: "", contagem: linha.contagem }]
                  : []
              return (
                <li key={linha.tipo}>
                  <button
                    type="button"
                    onClick={inativo ? undefined : () => navegarParaTipo(linha.tipo)}
                    disabled={inativo}
                    className={cn(
                      "grid w-full grid-cols-[180px_1fr_36px] items-center gap-3 rounded-md py-1.5 pl-2 pr-3 text-left",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      inativo ? "opacity-50" : "transition-colors hover:bg-ink-200"
                    )}
                    aria-label={`${linha.rotulo}: ${linha.contagem} escalas`}
                  >
                    <span
                      className={cn(
                        "truncate text-[13px]",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                      title={linha.rotulo}
                    >
                      {linha.rotulo}
                    </span>
                    <div className="relative h-3 overflow-hidden rounded-full bg-ink-100">
                      <div
                        className="flex h-full overflow-hidden rounded-full transition-[width] duration-300"
                        style={{ width: `${pctBarra}%` }}
                      >
                        {segmentos.map((seg) => {
                          const segPct =
                            linha.contagem > 0 ? (seg.contagem / linha.contagem) * 100 : 0
                          return (
                            <span
                              key={`${linha.tipo}-${seg.modelo_id}`}
                              title={`${seg.nome || "Total"}: ${seg.contagem}`}
                              className="h-full"
                              style={{
                                width: `${segPct}%`,
                                background:
                                  seg.modelo_id === "_agregado"
                                    ? "var(--warn-500)"
                                    : mapaCores.get(seg.modelo_id) ?? "var(--text-muted)",
                              }}
                            />
                          )
                        })}
                      </div>
                    </div>
                    <span
                      className={cn(
                        "text-right font-mono text-xs font-medium tabular-nums",
                        inativo ? "text-text-muted" : "text-text-primary"
                      )}
                    >
                      {linha.contagem}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {data.total > 0 ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-foreground/5 pt-3">
            <Legenda linhas={linhas} cores={mapaCores} />
            <button
              type="button"
              onClick={onAbrirTodas}
              className="text-xs font-medium text-text-muted underline-offset-2 hover:text-text-primary hover:underline focus-visible:text-text-primary focus-visible:underline focus-visible:outline-none"
            >
              Ver lista completa
            </button>
          </div>
        ) : null}
      </div>
    </section>
  )
}

function Legenda({
  linhas,
  cores,
}: {
  linhas: MotivoEscaladaPorTipo[]
  cores: Map<string, string>
}) {
  const mapa = new Map<string, { nome: string; total: number }>()
  for (const linha of linhas) {
    for (const seg of linha.por_modelo) {
      const atual = mapa.get(seg.modelo_id) ?? { nome: seg.nome, total: 0 }
      atual.total += seg.contagem
      mapa.set(seg.modelo_id, atual)
    }
  }
  const modelos = Array.from(mapa.entries())
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 6)
  if (modelos.length === 0) return null
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {modelos.map(([id, { nome, total }]) => (
        <li key={id} className="flex items-center gap-2 text-[11px] text-text-muted">
          <span
            aria-hidden
            className="inline-block h-2 w-2 rounded-sm"
            style={{ background: cores.get(id) ?? "var(--text-muted)" }}
          />
          <span>{nome}</span>
          <span className="font-mono tabular-nums">{total}</span>
        </li>
      ))}
    </ul>
  )
}
