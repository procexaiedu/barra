import type { MapaMetrica } from "@/lib/mapaMetrica"
import { RAMPA_DIVERGENTE_RGB } from "@/lib/cores/divergente"
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
  /** Modo Comparar (MAPA-14): valor da métrica corrente em cada recorte e o
   *  delta `B − A`. Presentes só quando o hexbin foi criado com `comparar=true`. */
  somaA?: number
  somaB?: number
  delta?: number
}

export interface HexbinOpts {
  pontos: MapaClientePonto[]
  metrica: MapaMetrica
  onClickFavo: (info: HexbinPickedInfo) => void
  /** MAPA-14: quando true, a layer agrega o delta B−A por célula (usando
   *  `getColorValue`) e pinta com a paleta divergente. Cada ponto traz
   *  `recorte: "A" | "B"`; pontos sem recorte são ignorados na agregação. */
  comparar?: boolean
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

// Aproximação em graus do RADIUS_M para o proxy de bin do MAPA-14. Sem ser o
// mesmo grid do d3-hexbin (que a HexagonLayer usa), serve só para estimar a
// cota superior `maxAbs` do delta — `colorDomain` é o uso final, não a posição
// dos favos. 1° latitude ≈ 111 km, então 3000m ≈ 0.027°. Bins um pouco maiores
// que o real OK (subestima maxAbs marginalmente — qualquer cota superior limpa
// o problema do colorDomain assimétrico).
const GRID_DEG = RADIUS_M / 111_000

// MAPA-14: agrega deltas (Σ peso(B) − Σ peso(A)) por célula aproximada. Usado só
// para encontrar `maxAbs` e fixar um `colorDomain` simétrico — sem isso, a paleta
// divergente vira sequencial (deck.gl usa [min,max] dos valores por default).
function somaDeltasPorCelula(
  pontos: ReadonlyArray<MapaClientePonto>,
  peso: (p: MapaClientePonto) => number,
): number[] {
  const acc = new Map<string, { a: number; b: number }>()
  for (const p of pontos) {
    const cx = Math.round(p.latitude / GRID_DEG)
    const cy = Math.round(p.longitude / GRID_DEG)
    const key = `${cx}:${cy}`
    const slot = acc.get(key) ?? { a: 0, b: 0 }
    if (p.recorte === "A") slot.a += peso(p)
    else if (p.recorte === "B") slot.b += peso(p)
    acc.set(key, slot)
  }
  return Array.from(acc.values(), (s) => s.b - s.a)
}

export async function criarHexbinOverlay(
  map: google.maps.Map,
  opts: HexbinOpts,
): Promise<HexbinHandle> {
  const [{ GoogleMapsOverlay }, { HexagonLayer }] = await Promise.all([
    import("@deck.gl/google-maps"),
    import("@deck.gl/aggregation-layers"),
  ])

  function construirLayer(o: HexbinOpts) {
    const peso = pesoFn(o.metrica)
    if (o.comparar) {
      // MAPA-14: o colorValue de cada célula é o delta `Σ peso(B) − Σ peso(A)`.
      // `colorDomain` simétrico em torno de zero garante que o creme (cor do
      // meio da paleta) caia exatamente no neutro — sem isso, a paleta
      // divergente vira sequencial. `getColorValue` substitui
      // `colorAggregation`/`getColorWeight` (deck.gl exige um OU o outro).
      const deltas = somaDeltasPorCelula(o.pontos, peso)
      const maxAbs = Math.max(0, ...deltas.map((d) => Math.abs(d)))
      // `Math.max(1, maxAbs)` evita domínio [0,0] quando todos os deltas são 0
      // (pintaria tudo na cor MAX da rampa). Com 1, células com delta=0 caem
      // no neutro e o restante é proporcional.
      const dominio: [number, number] = [-Math.max(1, maxAbs), Math.max(1, maxAbs)]
      return new HexagonLayer<MapaClientePonto>({
        id: "clientes-hexbin-delta",
        data: o.pontos,
        getPosition: (p) => [p.longitude, p.latitude],
        radius: RADIUS_M,
        colorRange: RAMPA_DIVERGENTE_RGB.map(([r, g, b]) => [r, g, b]),
        colorDomain: dominio,
        extruded: false,
        pickable: true,
        gpuAggregation: false,
        getColorValue: (points) => {
          let somaA = 0
          let somaB = 0
          for (const p of points) {
            if (p.recorte === "A") somaA += peso(p)
            else if (p.recorte === "B") somaB += peso(p)
          }
          return somaB - somaA
        },
        onClick: (info) => {
          const obj = info.object as
            | { points?: ReadonlyArray<{ source: MapaClientePonto }> }
            | null
          if (!obj?.points || !info.coordinate) return false
          const lista = obj.points.map((p) => p.source)
          const somaA = lista
            .filter((p) => p.recorte === "A")
            .reduce((s, p) => s + peso(p), 0)
          const somaB = lista
            .filter((p) => p.recorte === "B")
            .reduce((s, p) => s + peso(p), 0)
          o.onClickFavo({
            count: lista.length,
            somaValor: lista.reduce((s, p) => s + Number(p.valor_total), 0),
            somaAtendimentos: lista.reduce((s, p) => s + p.total_atendimentos, 0),
            centroide: { lng: info.coordinate[0], lat: info.coordinate[1] },
            somaA,
            somaB,
            delta: somaB - somaA,
          })
          return true
        },
      })
    }
    const colorRange = lerRampaSeq()
    return new HexagonLayer<MapaClientePonto>({
      id: "clientes-hexbin",
      data: o.pontos,
      getPosition: (p) => [p.longitude, p.latitude],
      radius: RADIUS_M,
      colorAggregation: "SUM",
      colorRange,
      extruded: false,
      pickable: true,
      // GPU aggregation desligado: complementa o `interleaved:false` do overlay.
      // A textura intermediária da aggregation no v9.3.x dessincroniza com a
      // projeção do Maps Vector durante o pan (fractional zoom), colapsando
      // todos os pontos num bin único renderizado como quad fullscreen na cor
      // mínima da rampa (--seq-1). CPU path (d3-hexbin) calcula os bins em JS
      // sem depender dessa textura — sem perda perceptível com 30-100 pontos.
      gpuAggregation: false,
      getColorWeight: peso,
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
