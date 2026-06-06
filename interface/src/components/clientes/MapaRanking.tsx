"use client"

import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import type { MapaMetrica } from "@/lib/mapaMetrica"
import type { MapaClientePonto } from "@/tipos/clientes"

// MAPA-4: ranking lateral de bairros agregado client-side a partir dos pontos do
// endpoint. Métrica e ordenação seguem o seletor do MAPA-1.
//
// N=10 é decisão arbitrária deste módulo (documentada no PR); ajustável depois.
const TOP_N = 10
const NUM_FMT = new Intl.NumberFormat("pt-BR")

/** Chave de agrupamento: `bairro` → `endereco_formatado` → "sem bairro". */
export function chaveBairro(ponto: MapaClientePonto): string {
  return (
    ponto.bairro?.trim() ||
    ponto.endereco_formatado?.trim() ||
    "sem bairro"
  )
}

interface ItemRanking {
  chave: string
  valor: number
}

function agregar(
  pontos: readonly MapaClientePonto[],
  metrica: MapaMetrica,
): ItemRanking[] {
  const acc = new Map<string, number>()
  for (const p of pontos) {
    const k = chaveBairro(p)
    const v =
      metrica === "valor"
        ? Number(p.valor_total)
        : metrica === "atendimentos"
          ? p.total_atendimentos
          : 1
    acc.set(k, (acc.get(k) ?? 0) + v)
  }
  return [...acc.entries()]
    .map(([chave, valor]) => ({ chave, valor }))
    .sort((a, b) => b.valor - a.valor)
    .slice(0, TOP_N)
}

function formatarValor(metrica: MapaMetrica, n: number): string {
  if (metrica === "valor") return formatBRL(n)
  return NUM_FMT.format(n)
}

export function MapaRanking({
  pontos,
  metrica,
  onSelectBairro,
  className,
}: {
  pontos: MapaClientePonto[]
  metrica: MapaMetrica
  onSelectBairro: (chave: string) => void
  className?: string
}) {
  const itens = agregar(pontos, metrica)
  const rotulo =
    metrica === "valor"
      ? "R$ fechado"
      : metrica === "atendimentos"
        ? "Atendimentos"
        : "Clientes"

  return (
    <aside
      aria-label="Bairros que mais aparecem no mapa"
      className={cn(
        "flex h-full w-[240px] shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card",
        className
      )}
    >
      <div className="border-b border-border px-3 py-2">
        <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-secondary">
          Top <span className="font-mono tabular-nums">{TOP_N}</span> bairros
        </div>
        <div className="text-[11px] text-text-muted">ordenado por {rotulo}</div>
      </div>
      {itens.length === 0 ? (
        <div className="px-3 py-4 text-[12px] text-text-muted">
          Nenhum cliente nos filtros atuais.
        </div>
      ) : (
        <ol className="flex-1 divide-y divide-border overflow-y-auto">
          {itens.map((item, index) => (
            <li key={item.chave}>
              <button
                type="button"
                onClick={() => onSelectBairro(item.chave)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                <span className="w-5 shrink-0 font-mono tabular-nums text-text-muted">
                  {index + 1}
                </span>
                <span
                  className="min-w-0 flex-1 truncate text-text-primary"
                  title={item.chave}
                >
                  {item.chave}
                </span>
                <span className="font-mono tabular-nums text-text-secondary">
                  {formatarValor(metrica, item.valor)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </aside>
  )
}
