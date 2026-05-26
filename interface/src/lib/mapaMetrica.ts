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

/**
 * Modo de marcador do mapa de pontos (MAPA-2). Default na UI = "bolhas".
 * Só faz sentido quando modoCor==='metrica' — em "desfecho"/"perfil" o
 * marcador é sempre o PinElement colorido (MAPA-3/10).
 *  - "bolhas": círculo dimensionado (raio sqrt-escalado) e colorido pela métrica.
 *  - "pins":   AdvancedMarker default (sem peso visual da métrica).
 */
export type MapaModoMarker = "pins" | "bolhas"

/**
 * Camada do mapa (MAPA-6). Default na UI = "bolhas" (preserva a Fase 1).
 *  - "bolhas": 1 marcador por cliente (modo `MapaModoMarker` + modo de cor).
 *  - "hexbin": GoogleMapsOverlay+HexagonLayer (deck.gl), favos coloridos pela
 *              rampa --seq-* SOMANDO a métrica selecionada. O seletor de cor
 *              (`ModoCor`) é ocultado nesta camada — favo agrega pontos de
 *              desfechos/perfis mistos, então só "Por métrica" faz sentido.
 */
export type MapaCamada = "bolhas" | "hexbin"

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

/** Peso do ponto na métrica (1 quando "clientes" — cada ponto vale um). */
export function pesoPonto(ponto: MapaClientePonto, metrica: MapaMetrica): number {
  if (metrica === "clientes") return 1
  if (metrica === "valor") return Number(ponto.valor_total)
  return ponto.total_atendimentos
}

/**
 * Normalização [0..1] do peso dentro dos limites. Caso degenerado
 * (sem limites úteis ou min==max) → 0.5: bolhas uniformes no tamanho/cor
 * central, conforme nota do roadmap MAPA-2 sobre a métrica "clientes".
 */
export function normalizarPeso(
  peso: number,
  limites: { min: number; max: number } | null,
): number {
  if (!limites || limites.min === limites.max) return 0.5
  const t = (peso - limites.min) / (limites.max - limites.min)
  return Math.min(1, Math.max(0, t))
}

// Raio da bolha em px. Escala `sqrt` para que a ÁREA do círculo seja
// proporcional ao valor (não o raio) — decisão fechada no roadmap MAPA-2.
const RAIO_MIN_PX = 8
const RAIO_MAX_PX = 28

export function raioBolha(t: number): number {
  return RAIO_MIN_PX + (RAIO_MAX_PX - RAIO_MIN_PX) * Math.sqrt(t)
}

/** Cor da bolha — discretiza t em 5 buckets da `RAMPA_SEQ` (CSS vars, respeita tema). */
export function corBolha(t: number): string {
  const idx = Math.min(4, Math.max(0, Math.floor(t * 5)))
  return RAMPA_SEQ[idx]
}
