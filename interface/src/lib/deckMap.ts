import type { MapaClientePonto } from "@/tipos/clientes"
import type { MapaMetrica } from "@/lib/mapaMetrica"

// Overlay deck.gl + camada Hexbin sobre o mesmo `google.maps.Map` (MAPA-6 do roadmap).
// As libs de runtime (`@deck.gl/google-maps`, `@deck.gl/aggregation-layers`) são carregadas
// via `await import()` para ficarem fora do bundle inicial do Mapa de clientes.

type RGB = [number, number, number]

export interface HexCelulaInfo {
  /** Quantidade de pontos (clientes) agregados na célula. */
  quantidade: number
  /** Soma da métrica selecionada nos pontos da célula. */
  somaMetrica: number
  /** Coordenada [lng, lat] do clique, para abrir InfoWindow. */
  coordenada: [number, number]
}

export interface DeckOverlayHandle {
  atualizar: (params: { pontos: MapaClientePonto[]; metrica: MapaMetrica }) => void
  destruir: () => void
}

function pesoDoPonto(ponto: MapaClientePonto, metrica: MapaMetrica): number {
  if (metrica === "valor") return Number(ponto.valor_total)
  if (metrica === "atendimentos") return ponto.total_atendimentos
  return 1
}

// Lê a rampa sequencial do tema atual (--seq-1..5 em globals.css) para que os favos
// usem as mesmas cores da legenda. Em SSR ou tema ainda não aplicado retorna fallback.
function rampaTema(): RGB[] {
  if (typeof window === "undefined") return RAMPA_FALLBACK
  const estilo = getComputedStyle(document.documentElement)
  const cores: RGB[] = []
  for (let i = 1; i <= 5; i++) {
    const hex = estilo.getPropertyValue(`--seq-${i}`).trim()
    const rgb = hexParaRgb(hex)
    if (!rgb) return RAMPA_FALLBACK
    cores.push(rgb)
  }
  return cores
}

// Espelho RGB da rampa dourada do tema escuro — usado se getComputedStyle falhar.
const RAMPA_FALLBACK: RGB[] = [
  [0x1a, 0x16, 0x06],
  [0x4a, 0x3f, 0x25],
  [0x8c, 0x78, 0x48],
  [0xc4, 0xa9, 0x61],
  [0xe6, 0xcb, 0x7a],
]

function hexParaRgb(hex: string): RGB | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

export async function criarOverlayHexbin(params: {
  map: google.maps.Map
  pontos: MapaClientePonto[]
  metrica: MapaMetrica
  onClickCelula: (info: HexCelulaInfo) => void
}): Promise<DeckOverlayHandle> {
  const [{ GoogleMapsOverlay }, { HexagonLayer }] = await Promise.all([
    import("@deck.gl/google-maps"),
    import("@deck.gl/aggregation-layers"),
  ])

  let pontosAtuais = params.pontos
  let metricaAtual = params.metrica
  const corDaRampa = rampaTema()

  // Raio em metros do hexágono agregador. 3 km cobre um bairro/setor sem dissolver o
  // sinal num dado esparso; calibração inicial — ajustar quando o volume crescer.
  const RAIO_METROS = 3000

  function montarLayer() {
    return new HexagonLayer<MapaClientePonto>({
      id: "clientes-hexbin",
      data: pontosAtuais,
      getPosition: (p) => [p.longitude, p.latitude],
      getColorWeight: (p) => pesoDoPonto(p, metricaAtual),
      colorAggregation: "SUM",
      extruded: false,
      pickable: true,
      radius: RAIO_METROS,
      colorRange: corDaRampa,
      onClick: (info) => {
        const objeto = info?.object as { points?: { source: MapaClientePonto }[] } | null
        if (!objeto?.points) return false
        const soma = objeto.points.reduce(
          (acc, item) => acc + pesoDoPonto(item.source, metricaAtual),
          0,
        )
        const coord = (info.coordinate ?? [0, 0]) as [number, number]
        params.onClickCelula({
          quantidade: objeto.points.length,
          somaMetrica: soma,
          coordenada: [coord[0], coord[1]],
        })
        return true
      },
    })
  }

  const overlay = new GoogleMapsOverlay({ layers: [montarLayer()] })
  overlay.setMap(params.map)

  return {
    atualizar({ pontos, metrica }) {
      pontosAtuais = pontos
      metricaAtual = metrica
      overlay.setProps({ layers: [montarLayer()] })
    },
    destruir() {
      overlay.setMap(null)
      overlay.finalize()
    },
  }
}
