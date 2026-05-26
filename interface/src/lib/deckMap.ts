import type { MapaMetrica } from "@/lib/mapaMetrica"
import type { MapaClientePonto } from "@/tipos/clientes"

// deck.gl GoogleMapsOverlay + HexagonLayer (MAPA-6).
//
// Os imports do deck.gl são DINÂMICOS — chunk separado, fora do bundle inicial
// (restrição 1 do roadmap: deck.gl só carrega ao alternar para Hexbin). Quem
// chama recebe um handle imperativo com `atualizar`/`dispose`.
//
// HeatmapLayer de google.maps.visualization é proibida (deprecada maio/2025);
// usamos deck.gl conforme ADR 0008 / roadmap MAPA-6.

export interface HexbinPickedInfo {
  count: number
  somaValor: number
  somaAtendimentos: number
  centroide: { lat: number; lng: number }
}

export interface HexbinOpts {
  pontos: MapaClientePonto[]
  metrica: MapaMetrica
  onClickFavo: (info: HexbinPickedInfo) => void
}

export interface HexbinHandle {
  atualizar: (opts: HexbinOpts) => void
  dispose: () => void
}

// MAPA-7: HeatmapLayer KDE. Não é um agregador discreto como o Hexbin — é um
// campo contínuo, então não há "célula" para clicar e portanto sem onClick. A
// honestidade do calor depende de volume: o componente esconde/desabilita o
// toggle quando `pontos.length < LIMIAR_CALOR_MIN_PONTOS` (ver mapaMetrica.ts).
export interface CalorOpts {
  pontos: MapaClientePonto[]
  metrica: MapaMetrica
}

export interface CalorHandle {
  atualizar: (opts: CalorOpts) => void
  dispose: () => void
}

// Raio do hexágono em metros (decisão MAPA-6: 3 km — meio-termo para dado
// esparso do P0; calibrar quando volume crescer).
const RADIUS_M = 3000

export async function criarHexbinOverlay(
  map: google.maps.Map,
  opts: HexbinOpts,
): Promise<HexbinHandle> {
  const [{ GoogleMapsOverlay }, { HexagonLayer }] = await Promise.all([
    import("@deck.gl/google-maps"),
    import("@deck.gl/aggregation-layers"),
  ])

  const colorRange = lerRampaSeq()

  function construirLayer(o: HexbinOpts) {
    return new HexagonLayer<MapaClientePonto>({
      id: "clientes-hexbin",
      data: o.pontos,
      getPosition: (p) => [p.longitude, p.latitude],
      radius: RADIUS_M,
      colorAggregation: "SUM",
      colorRange,
      extruded: false,
      pickable: true,
      getColorWeight: pesoFn(o.metrica),
      onClick: (info) => {
        const obj = info.object as
          | { points?: ReadonlyArray<{ source: MapaClientePonto }> }
          | null
        if (!obj?.points || !info.coordinate) return false
        const lista = obj.points.map((p) => p.source)
        o.onClickFavo({
          count: lista.length,
          somaValor: lista.reduce((s, p) => s + Number(p.valor_total), 0),
          somaAtendimentos: lista.reduce((s, p) => s + p.total_atendimentos, 0),
          centroide: { lng: info.coordinate[0], lat: info.coordinate[1] },
        })
        return true
      },
    })
  }

  // `interleaved:false` é OBRIGATÓRIO para aggregation layers (HexagonLayer/
  // HeatmapLayer) sobre Google Maps Vector (qualquer mapa com `mapId`). O
  // default `true` compartilha o WebGL2 context com o Maps e quebra o
  // render-to-texture intermediário — o sintoma é o overlay renderizar num
  // viewport degenerado (ex.: borrão preso no canto superior-esquerdo) e o
  // luma.gl emitir "Binding weightsTexture not set". Release notes do v9.3
  // confirmam o caminho: usar canvas separado garante posição DOM correta.
  const overlay = new GoogleMapsOverlay({
    interleaved: false,
    layers: [construirLayer(opts)],
  })
  overlay.setMap(map)

  return {
    atualizar(novoOpts) {
      overlay.setProps({ layers: [construirLayer(novoOpts)] })
    },
    dispose() {
      overlay.setMap(null)
      overlay.finalize()
    },
  }
}

// MAPA-7: cria o overlay deck.gl com HeatmapLayer KDE. Paralelo ao
// `criarHexbinOverlay` (mesma forma de handle/opts, sem `onClick`). iOS Safari
// tem limitação histórica de textura float que afeta o HeatmapLayer; painel é
// desktop-only, então só registramos a limitação aqui — não tentamos workaround.
export async function criarCalorOverlay(
  map: google.maps.Map,
  opts: CalorOpts,
): Promise<CalorHandle> {
  const [{ GoogleMapsOverlay }, { HeatmapLayer }] = await Promise.all([
    import("@deck.gl/google-maps"),
    import("@deck.gl/aggregation-layers"),
  ])

  const colorRange = lerRampaSeq()

  function construirLayer(o: CalorOpts) {
    return new HeatmapLayer<MapaClientePonto>({
      id: "clientes-calor",
      data: o.pontos,
      getPosition: (p) => [p.longitude, p.latitude],
      getWeight: pesoFn(o.metrica),
      aggregation: "SUM",
      colorRange,
      // radiusPixels/intensity/threshold ficam nos defaults do deck.gl (60/1/0.05).
      // Calibrar quando volume crescer — antes disso, ajustar fino é palpite.
    })
  }

  // `interleaved:false`: ver nota no `criarHexbinOverlay` — mesmo motivo (o
  // HeatmapLayer é o caso clássico do bug; o sintoma reportado em prod foi um
  // borrão fraco preso no canto superior-esquerdo do mapa).
  const overlay = new GoogleMapsOverlay({
    interleaved: false,
    layers: [construirLayer(opts)],
  })
  overlay.setMap(map)

  return {
    atualizar(novoOpts) {
      overlay.setProps({ layers: [construirLayer(novoOpts)] })
    },
    dispose() {
      overlay.setMap(null)
      overlay.finalize()
    },
  }
}

function pesoFn(metrica: MapaMetrica): (p: MapaClientePonto) => number {
  if (metrica === "valor") return (p) => Number(p.valor_total)
  if (metrica === "atendimentos") return (p) => p.total_atendimentos
  // "clientes" → cada ponto vale 1 (com colorAggregation:'SUM' equivale a COUNT).
  return () => 1
}

// Lê a rampa --seq-1..5 do tema (globals.css). HexagonLayer espera tuplas RGB
// 0..255, não CSS vars — copiamos as cores no momento da criação. Em SSR ou se
// a leitura falhar, cai para a rampa do tema escuro (claro→escuro vira
// escuro→claro: igual ao gradiente da legenda). Visualmente coerente com
// LegendaEscala (MapaControles.tsx).
function lerRampaSeq(): Array<[number, number, number]> {
  const fallbackDark: Array<[number, number, number]> = [
    [26, 22, 6],
    [74, 63, 37],
    [140, 120, 72],
    [196, 169, 97],
    [230, 203, 122],
  ]
  if (typeof window === "undefined") return fallbackDark
  try {
    const styles = getComputedStyle(document.documentElement)
    const hexs = [1, 2, 3, 4, 5].map((i) =>
      styles.getPropertyValue(`--seq-${i}`).trim(),
    )
    if (hexs.some((c) => !c)) return fallbackDark
    return hexs.map(parseHex)
  } catch {
    return fallbackDark
  }
}

function parseHex(hex: string): [number, number, number] {
  const m = hex.match(/^#?([0-9a-f]{6})$/i)
  if (!m) return [128, 128, 128]
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
