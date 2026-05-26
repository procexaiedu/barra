import type { MapaClientePonto } from "@/tipos/clientes"

/**
 * Métrica de "peso" do Mapa de clientes (MAPA-1, espinha dorsal da Fase 1).
 * Reusada pelas camadas seguintes (bolhas/hexbin/KDE) e pelo ranking lateral.
 *  - "valor":        R$ fechado (`valor_total`) — default.
 *  - "atendimentos": nº de atendimentos (`total_atendimentos`).
 *  - "clientes":     contagem de pontos (cada ponto = 1 cliente). Degenera nas
 *                    camadas por ponto (todas as bolhas iguais); só faz pleno
 *                    sentido nas camadas de agregação (MAPA-6/7).
 */
export type MapaMetrica = "valor" | "atendimentos" | "clientes"

export interface MapaMetricaOpcao {
  id: MapaMetrica
  label: string
  /** Tooltip curto exibido no botão do seletor — desenha a intenção da métrica. */
  tooltip: string
}

export const OPCOES_METRICA: readonly MapaMetricaOpcao[] = [
  {
    id: "valor",
    label: "R$ fechado",
    tooltip: "Soma do valor final dos atendimentos fechados de cada cliente.",
  },
  {
    id: "atendimentos",
    label: "Atendimentos",
    tooltip: "Número de atendimentos por cliente (todas as modelos).",
  },
  {
    id: "clientes",
    label: "Clientes",
    tooltip:
      "Cada ponto é 1 cliente. Só faz pleno sentido nas camadas de agregação (Hexbin/Calor).",
  },
] as const

/**
 * Rampa sequencial dourada do tema (globals.css). Em modo escuro a luminância
 * sobe de --seq-1 (#1A1606) a --seq-5 (#E6CB7A). Use como `background` em CSS
 * via `var(--seq-N)` — não resolva a cor em JS para respeitar o tema.
 */
export const RAMPA_SEQ = [
  "var(--seq-1)",
  "var(--seq-2)",
  "var(--seq-3)",
  "var(--seq-4)",
  "var(--seq-5)",
] as const

/**
 * `min`/`max` da métrica nos pontos atuais. Retorna `null` quando não há min/max
 * útil — "clientes" (degenerado: cada ponto vale 1) ou lista vazia. Quem consome
 * trata `null` exibindo um placeholder em vez de números.
 */
export function limitesMetrica(
  pontos: readonly MapaClientePonto[],
  metrica: MapaMetrica,
): { min: number; max: number } | null {
  if (metrica === "clientes" || pontos.length === 0) return null
  const valores = pontos.map((p) =>
    metrica === "valor" ? Number(p.valor_total) : p.total_atendimentos,
  )
  return { min: Math.min(...valores), max: Math.max(...valores) }
}
