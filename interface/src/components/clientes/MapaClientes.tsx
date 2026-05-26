"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarkerClusterer } from "@googlemaps/markerclusterer"
import { carregarBiblioteca, googleMapsApiKey, googleMapsMapId } from "@/lib/googleMaps"
import { formatBRL } from "@/lib/formatters"
import {
  corBolha,
  limitesMetrica,
  normalizarPeso,
  pesoPonto,
  raioBolha,
  type MapaCamada,
  type MapaMetrica,
} from "@/lib/mapaMetrica"
import {
  criarCalorOverlay,
  criarHexbinOverlay,
  type CalorHandle,
  type HexbinHandle,
} from "@/lib/deckMap"
import {
  COR_PERFIL,
  COR_PERFIL_SEM,
  LegendaDesfecho,
  LegendaEscala,
  LegendaPerfil,
  SeletorCamada,
  SeletorMetrica,
  SeletorModoCor,
  corPorDesfecho,
  type ModoCor,
} from "@/components/clientes/MapaControles"
import { MapaRanking, chaveBairro } from "@/components/clientes/MapaRanking"
import { rotuloPerfil } from "@/lib/perfilFisico"
import type { EstadoAtendimento, MapaClientePonto, PerfilFisico } from "@/tipos/clientes"

// Centro aproximado do Brasil para a abertura, antes do fit nos pins (ADR 0008).
const CENTRO_BRASIL = { lat: -14.235, lng: -51.925 }

type Status = "idle" | "loading" | "success" | "error"

export function MapaClientes({
  pontos,
  totalSemLocalizacao,
  status,
  error,
  onRetry,
  onFiltrarBairro,
}: {
  pontos: MapaClientePonto[]
  totalSemLocalizacao: number
  status: Status
  error: string | null
  onRetry: () => void
  /** MAPA-12: liga o mapa à Lista — informa o bairro do ponto clicado ao pai. */
  onFiltrarBairro?: (bairro: string) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<google.maps.Map | null>(null)
  const infoRef = useRef<google.maps.InfoWindow | null>(null)
  const clustererRef = useRef<MarkerClusterer | null>(null)
  // MAPA-6: handle do GoogleMapsOverlay+HexagonLayer. Existe só enquanto
  // camada==='hexbin' — criamos no efeito de entrada e descartamos ao sair.
  const hexbinRef = useRef<HexbinHandle | null>(null)
  // Sentinela para descartar overlays criados em vão (alterna rápido de
  // bolhas→hexbin→bolhas antes do import dinâmico resolver).
  const hexbinSeqRef = useRef(0)
  // MAPA-7: handle do GoogleMapsOverlay+HeatmapLayer (KDE). Existe só enquanto
  // camada==='calor'. Paralelo ao hexbin; mantemos refs separadas para que
  // alternar entre as camadas descarte o overlay anterior sem ambiguidade.
  const calorRef = useRef<CalorHandle | null>(null)
  const calorSeqRef = useRef(0)
  // Marcadores guardam o bairro (destaque MAPA-4), o estado (cor MAPA-3), os perfis
  // declarados (cor MAPA-10) e o peso normalizado (tamanho/cor de bolha MAPA-2) para
  // que os efeitos re-renderizem sem refazer a varredura.
  const markersRef = useRef<
    Array<{
      marker: google.maps.marker.AdvancedMarkerElement
      chave: string
      estado: EstadoAtendimento
      perfis: PerfilFisico[]
      peso: number
      /** Handler de clique reusado quando aplicarDestaque troca o content. */
      abrirInfo: () => void
    }>
  >([])
  const [mapPronto, setMapPronto] = useState(false)
  // Métrica do mapa (MAPA-1, espinha dorsal). Default = R$ fechado, conforme spec.
  const [metrica, setMetrica] = useState<MapaMetrica>("valor")
  // MAPA-3: modo de cor dos pontos. Ortogonal à métrica (que rege o tamanho).
  // Default "metrica" preserva o comportamento prévio. Em "metrica" o marker é
  // sempre bolha sqrt-escalada; em "desfecho"/"perfil" é PinElement colorido.
  const [modoCor, setModoCor] = useState<ModoCor>("metrica")
  // MAPA-6: camada atual. Default "bolhas" — preserva a Fase 1.
  const [camada, setCamada] = useState<MapaCamada>("bolhas")
  // MAPA-4: bairro selecionado no ranking lateral; controla pan + destaque das bolhas.
  const [bairroSelecionado, setBairroSelecionado] = useState<string | null>(null)

  // Redesenha os marcadores a partir dos pontos atuais (puro side-effect imperativo no mapa).
  const desenharPontos = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    clustererRef.current?.clearMarkers()
    markersRef.current.forEach(({ marker }) => {
      marker.map = null
    })
    markersRef.current = []

    // MAPA-6/MAPA-7: nas camadas de agregação (Hexbin/Calor) só o overlay
    // deck.gl renderiza — markers/cluster ficam ocultos.
    if (camada !== "bolhas") return

    const limites = limitesMetrica(pontos, metrica)
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    for (const ponto of pontos) {
      const posicao = { lat: ponto.latitude, lng: ponto.longitude }
      const peso = normalizarPeso(pesoPonto(ponto, metrica), limites)
      const content = conteudoPorModo(modoCor, ponto, peso)
      const marker = new google.maps.marker.AdvancedMarkerElement({
        position: posicao,
        title: ponto.nome ?? "Cliente",
        content,
      })
      // Click via DOM no próprio `content`, não via `gmp-click` do AdvancedMarker.
      // A combinação MarkerClusterer 2.x + AdvancedMarker v=weekly + gmpClickable
      // estoura `TypeError: Cannot read properties of undefined (reading 'length')`
      // no marker.js interno do Google ao despachar o evento.
      const abrirInfo = () => {
        const info = infoRef.current
        if (!info) return
        info.setContent(conteudoInfo(ponto, onFiltrarBairro))
        info.open({ map, anchor: marker })
      }
      bindClickAoContent(content, abrirInfo)
      markersRef.current.push({
        marker,
        chave: chaveBairro(ponto),
        estado: ponto.estado,
        perfis: ponto.perfis,
        peso,
        abrirInfo,
      })
      markers.push(marker)
    }

    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({ map, markers })
    } else {
      clustererRef.current.addMarkers(markers)
    }
  }, [pontos, onFiltrarBairro, modoCor, metrica, camada])

  // Fit nos pontos só quando o conjunto muda — trocar métrica/modo/cor redesenha
  // sem reposicionar o mapa (preserva pan/zoom do usuário). MAPA-2 depende disso
  // para alternar bolhas sem perder o lugar.
  useEffect(() => {
    if (!mapPronto) return
    const map = mapRef.current
    if (!map || pontos.length === 0) return
    const bounds = new google.maps.LatLngBounds()
    for (const ponto of pontos) {
      bounds.extend({ lat: ponto.latitude, lng: ponto.longitude })
    }
    map.fitBounds(bounds, 64)
    // Um único ponto faz o fitBounds dar zoom máximo; limita para algo navegável.
    if (pontos.length === 1) {
      google.maps.event.addListenerOnce(map, "idle", () => {
        if ((map.getZoom() ?? 0) > 14) map.setZoom(14)
      })
    }
  }, [mapPronto, pontos])

  // MAPA-6/MAPA-7: dispose dos overlays deck.gl no unmount do componente. O
  // efeito principal só descarta quando `camada` muda; sem este cleanup, sair
  // da aba Mapa enquanto a camada está em Hexbin/Calor vazaria o overlay (e o
  // WebGL context dele).
  useEffect(() => {
    return () => {
      hexbinRef.current?.dispose()
      hexbinRef.current = null
      calorRef.current?.dispose()
      calorRef.current = null
    }
  }, [])

  // Inicializa o mapa uma vez (guardas cobrem o duplo-mount do StrictMode em dev).
  useEffect(() => {
    if (!googleMapsApiKey) return
    let cancelado = false
    Promise.all([
      carregarBiblioteca<google.maps.MapsLibrary>("maps"),
      carregarBiblioteca<google.maps.MarkerLibrary>("marker"),
    ])
      .then(([{ Map, InfoWindow }]) => {
        if (cancelado || !containerRef.current || mapRef.current) return
        const map = new Map(containerRef.current, {
          center: CENTRO_BRASIL,
          zoom: 4,
          mapId: googleMapsMapId,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
        })
        mapRef.current = map
        infoRef.current = new InfoWindow()
        // Espera o `idle` antes de liberar os overlays do deck.gl. Sem isso, o
        // primeiro `onDraw` do GoogleMapsOverlay roda com viewport degenerado
        // (zoom/center pré-layout), o que faz o HexagonLayer agregar `radius`
        // em metros contra um `unitsPerMeter` zero → todos os pontos colapsam
        // num bin único renderizado como fullscreen quad na cor MAX da rampa.
        // HexagonLayer não re-agrega no pan (agregação é world-space), então o
        // estado ruim fica fixo até unmount. HeatmapLayer não tem essa armadilha
        // porque usa `radiusPixels` em screen-space (sobrevive ao primeiro
        // viewport ruim sem precisar do gate).
        google.maps.event.addListenerOnce(map, "idle", () => {
          if (cancelado) return
          setMapPronto(true)
        })
      })
      .catch(() => {
        // Falha de carregamento da API: a UI segue mostrando o container vazio; o status
        // do fetch (loading/error) cobre o feedback de dados.
      })
    return () => {
      cancelado = true
    }
  }, [])

  // Redesenha quando o mapa fica pronto ou quando os pontos mudam.
  useEffect(() => {
    if (mapPronto) desenharPontos()
  }, [mapPronto, desenharPontos])

  // MAPA-4: destaque leve das bolhas do bairro selecionado. Roda depois de
  // `desenharPontos` (declarado abaixo) para reaplicar quando os pontos mudam.
  // Inclui `modoCor` nas deps para restaurar a aparência correta (cor por
  // desfecho/perfil ou bolha sqrt-escalada) ao deselecionar.
  useEffect(() => {
    aplicarDestaque(markersRef.current, bairroSelecionado, modoCor)
  }, [bairroSelecionado, mapPronto, pontos, modoCor])

  // MAPA-6: ciclo de vida do overlay deck.gl. Cria ao entrar em "hexbin"
  // (import dinâmico), atualiza quando pontos/métrica mudam, descarta ao sair.
  // O sequencial evita aplicar um overlay obsoleto se a camada virar antes do
  // import resolver (alternância rápida).
  useEffect(() => {
    if (!mapPronto) return
    const map = mapRef.current
    if (!map) return
    if (camada !== "hexbin") {
      hexbinRef.current?.dispose()
      hexbinRef.current = null
      return
    }
    const opts = {
      pontos,
      metrica,
      onClickFavo: (info: import("@/lib/deckMap").HexbinPickedInfo) => {
        const win = infoRef.current
        if (!win) return
        win.setContent(conteudoFavo(info, metrica))
        win.setPosition(info.centroide)
        win.open(map)
      },
    }
    if (hexbinRef.current) {
      hexbinRef.current.atualizar(opts)
      return
    }
    const seq = ++hexbinSeqRef.current
    let cancelado = false
    criarHexbinOverlay(map, opts)
      .then((handle) => {
        if (cancelado || seq !== hexbinSeqRef.current) {
          handle.dispose()
          return
        }
        hexbinRef.current = handle
      })
      .catch(() => {
        // Falha de import dinâmico: a camada Hexbin fica indisponível desta vez.
        // A UI continua mostrando o mapa (bolhas seguem funcionando ao voltar).
      })
    return () => {
      cancelado = true
    }
  }, [camada, pontos, metrica, mapPronto])

  // MAPA-7: ciclo de vida do overlay deck.gl Calor (HeatmapLayer KDE). Espelha
  // o do hexbin — diferença é que não há picking (campo contínuo). O guard de
  // honestidade (limiar mínimo de pontos) vive no SeletorCamada, que desabilita
  // o botão; se mesmo assim a camada for "calor" sem volume suficiente, o
  // overlay sobe e renderiza um borrão fraco — não é erro, é só feio.
  useEffect(() => {
    if (!mapPronto) return
    const map = mapRef.current
    if (!map) return
    if (camada !== "calor") {
      calorRef.current?.dispose()
      calorRef.current = null
      return
    }
    const opts = { pontos, metrica }
    if (calorRef.current) {
      calorRef.current.atualizar(opts)
      return
    }
    const seq = ++calorSeqRef.current
    let cancelado = false
    criarCalorOverlay(map, opts)
      .then((handle) => {
        if (cancelado || seq !== calorSeqRef.current) {
          handle.dispose()
          return
        }
        calorRef.current = handle
      })
      .catch(() => {
        // Falha de import dinâmico: a camada Calor fica indisponível desta vez.
        // A UI continua mostrando o mapa (bolhas/hexbin seguem funcionando).
      })
    return () => {
      cancelado = true
    }
  }, [camada, pontos, metrica, mapPronto])

  // MAPA-4: pan do mapa para o centroide das bolhas do bairro escolhido.
  const handleSelectBairro = useCallback(
    (chave: string) => {
      setBairroSelecionado(chave)
      const map = mapRef.current
      if (!map) return
      const pts = pontos.filter((p) => chaveBairro(p) === chave)
      if (pts.length === 0) return
      const lat = pts.reduce((acc, p) => acc + p.latitude, 0) / pts.length
      const lng = pts.reduce((acc, p) => acc + p.longitude, 0) / pts.length
      map.panTo({ lat, lng })
    },
    [pontos],
  )

  if (!googleMapsApiKey) {
    return (
      <div className="grid place-items-center rounded-lg border border-border bg-card p-8 text-center text-sm text-text-muted">
        Configure <code className="mx-1">NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code> para habilitar o mapa.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-text-muted">
        <div className="flex flex-wrap items-center gap-2">
          <span>
            {pontos.length} cliente{pontos.length === 1 ? "" : "s"} no mapa
          </span>
          {totalSemLocalizacao > 0 && (
            <span className="rounded-full border border-border bg-card px-3 py-1">
              {totalSemLocalizacao} sem localização
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SeletorCamada
            camada={camada}
            pontosCount={pontos.length}
            onCamadaChange={setCamada}
          />
          <SeletorMetrica metrica={metrica} onMetricaChange={setMetrica} />
          {camada === "bolhas" && (
            <SeletorModoCor modo={modoCor} onModoChange={setModoCor} />
          )}
        </div>
      </div>
      <div className="flex h-[calc(100vh-300px)] min-h-[420px] gap-2">
        <div className="relative flex-1 overflow-hidden rounded-lg border border-border">
          <div ref={containerRef} className="h-full w-full" />
          <div className="absolute bottom-3 left-3">
            {/* Legenda contextual: só aparece o que realmente codifica algo no mapa.
                - Hexbin/Calor e Pontos+Por métrica → rampa --seq-* (LegendaEscala).
                - Pontos+Por desfecho → 3 baldes de cor (LegendaDesfecho).
                - Pontos+Por perfil → 6 categorias + Sem declaração (LegendaPerfil).
                Em todos os outros (camada ≠ Pontos), a cor é sempre da métrica. */}
            {camada === "bolhas" && modoCor === "desfecho" ? (
              <LegendaDesfecho />
            ) : camada === "bolhas" && modoCor === "perfil" ? (
              <LegendaPerfil />
            ) : (
              <LegendaEscala metrica={metrica} pontos={pontos} />
            )}
          </div>
          {status === "loading" && pontos.length === 0 && (
            <div className="absolute inset-0 grid place-items-center text-sm text-text-muted">
              Carregando mapa…
            </div>
          )}
          {status === "error" && (
            <div className="absolute inset-0 grid place-items-center gap-2 bg-card/80 text-sm text-state-lost">
              <span>{error ?? "Erro ao carregar o mapa."}</span>
              <button type="button" onClick={onRetry} className="underline underline-offset-2">
                Tentar de novo
              </button>
            </div>
          )}
          {status === "success" && pontos.length === 0 && (
            <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-text-muted">
              Nenhum cliente com localização (atendimento externo geocodificado) nos filtros atuais.
            </div>
          )}
        </div>
        <MapaRanking
          pontos={pontos}
          metrica={metrica}
          onSelectBairro={handleSelectBairro}
        />
      </div>
    </div>
  )
}

// Elemento DOM usado como `content` do AdvancedMarkerElement quando o bairro do
// ponto é o selecionado no ranking — substitui o pin padrão por um disco dourado
// com ring, suficiente para "destaque visual leve" sem reimplementar bolhas
// (que é a MAPA-2).
function criarConteudoDestaque(): HTMLElement {
  const el = document.createElement("div")
  el.style.cssText =
    "width:18px;height:18px;border-radius:50%;background:#E6CB7A;border:2px solid #1a1a1a;box-shadow:0 0 0 4px rgba(230,203,122,0.35);"
  return el
}

// Pin colorido pelo desfecho do atendimento que ancora o ponto (MAPA-3).
// PinElement é da própria lib `marker` que já carregamos.
function criarConteudoDesfecho(estado: EstadoAtendimento): HTMLElement {
  return new google.maps.marker.PinElement({
    background: corPorDesfecho(estado),
    borderColor: "#1a1a1a",
    glyphColor: "#1a1a1a",
  }).element
}

// Pin colorido pelo PRIMEIRO perfil declarado do cliente (MAPA-10, ADR 0006).
// Cliente sem declaração entra como cinza neutro — nunca usa o breakdown calculado.
function criarConteudoPerfil(perfis: PerfilFisico[]): HTMLElement {
  const cor = perfis.length > 0 ? COR_PERFIL[perfis[0]] : COR_PERFIL_SEM
  return new google.maps.marker.PinElement({
    background: cor,
    borderColor: "#1a1a1a",
    glyphColor: "#1a1a1a",
  }).element
}

// Bolha do MAPA-2. AdvancedMarker ancora pelo bottom-center do `content`;
// `translateY(50%)` empurra o círculo para baixo de modo que seu centro caia
// exatamente na coordenada geográfica.
function criarConteudoBolha(peso: number): HTMLElement {
  const el = document.createElement("div")
  const diametro = 2 * raioBolha(peso)
  el.style.cssText = `width:${diametro}px;height:${diametro}px;border-radius:50%;background:${corBolha(peso)};border:2px solid rgba(255,255,255,0.9);box-shadow:0 1px 3px rgba(0,0,0,0.35);cursor:pointer;transform:translateY(50%);`
  return el
}

function conteudoPorModo(
  modoCor: ModoCor,
  ponto: MapaClientePonto,
  peso: number,
): HTMLElement {
  if (modoCor === "desfecho") return criarConteudoDesfecho(ponto.estado)
  if (modoCor === "perfil") return criarConteudoPerfil(ponto.perfis)
  // modoCor === "metrica": bolha sqrt-escalada (raio + cor pela rampa --seq-*).
  return criarConteudoBolha(peso)
}

// Mutação imperativa de instâncias do Google Maps — isolada aqui (fora do hook)
// porque o React Compiler trata refs como imutáveis no escopo de useEffect.
function aplicarDestaque(
  items: ReadonlyArray<{
    marker: google.maps.marker.AdvancedMarkerElement
    chave: string
    estado: EstadoAtendimento
    perfis: PerfilFisico[]
    peso: number
    abrirInfo: () => void
  }>,
  selecionado: string | null,
  modoCor: ModoCor,
) {
  for (const { marker, chave, estado, perfis, peso, abrirInfo } of items) {
    let novo: HTMLElement
    if (selecionado && chave === selecionado) {
      novo = criarConteudoDestaque()
    } else if (modoCor === "desfecho") {
      novo = criarConteudoDesfecho(estado)
    } else if (modoCor === "perfil") {
      novo = criarConteudoPerfil(perfis)
    } else {
      novo = criarConteudoBolha(peso)
    }
    marker.content = novo
    // Re-bind do click no novo content (`gmp-click` do AdvancedMarker está bugado
    // em combinação com MarkerClusterer — usamos DOM click no próprio content).
    bindClickAoContent(novo, abrirInfo)
  }
}

// Anexa um listener de click no `content` do AdvancedMarkerElement. Mantemos
// referência do handler em uma prop não-enumerável para conseguir limpar antes
// de reanexar quando `aplicarDestaque` troca o content. `cursor: pointer` é
// reforçado aqui mesmo em PinElement (que já tem cursor próprio) para uniformizar.
function bindClickAoContent(content: HTMLElement | null, handler: () => void): void {
  if (!content) return
  const prev = (content as HTMLElement & { __mapaClick?: (e: Event) => void })
    .__mapaClick
  if (prev) content.removeEventListener("click", prev)
  const wrapped = (e: Event) => {
    e.stopPropagation()
    handler()
  }
  content.addEventListener("click", wrapped)
  ;(content as HTMLElement & { __mapaClick?: (e: Event) => void }).__mapaClick =
    wrapped
  content.style.cursor = "pointer"
}

// InfoWindow é renderizada pelo Google num balão branco — cores fixas legíveis ali, não
// as do tema escuro do painel. Construímos um HTMLElement para poder anexar o listener
// do botão "Filtrar bairro" (MAPA-12) — textContent escapa dado livre automaticamente.
function conteudoInfo(
  ponto: MapaClientePonto,
  onFiltrarBairro?: (bairro: string) => void,
): HTMLElement {
  const container = document.createElement("div")
  container.style.cssText = "font-family: inherit; min-width: 180px; color: #1a1a1a;"

  const nome = document.createElement("div")
  nome.style.cssText = "font-weight: 600; margin-bottom: 2px;"
  nome.textContent = ponto.nome ?? "Cliente"
  container.appendChild(nome)

  const local = document.createElement("div")
  local.style.cssText = "color: #666; font-size: 12px;"
  local.textContent = ponto.bairro ?? ponto.endereco_formatado ?? "—"
  container.appendChild(local)

  const valor = formatBRL(Number(ponto.valor_total))
  const plural = ponto.total_atendimentos === 1 ? "atendimento" : "atendimentos"
  const totais = document.createElement("div")
  totais.style.cssText = "margin-top: 6px; font-size: 12px;"
  totais.textContent = `${ponto.total_atendimentos} ${plural} · ${valor}`
  container.appendChild(totais)

  // Última data + recorrência (MAPA-5). Degradam para "—" quando ausentes.
  const ultima = ponto.ultima_data ? formatarDataBR(ponto.ultima_data) : "—"
  const recorrencia =
    ponto.recorrente === undefined ? "—" : ponto.recorrente ? "Recorrente" : "Não recorrente"
  const meta = document.createElement("div")
  meta.style.cssText = "margin-top: 2px; font-size: 12px; color: #666;"
  meta.textContent = `Última: ${ultima} · ${recorrencia}`
  container.appendChild(meta)

  // Perfil físico DECLARADO (MAPA-10, ADR 0006). Lista todos quando >1 — o pin pega
  // só o primeiro como cor. Sem declaração, omite a linha (não confunde com "outra").
  if (ponto.perfis.length > 0) {
    const perfis = document.createElement("div")
    perfis.style.cssText = "margin-top: 4px; font-size: 12px; color: #666;"
    perfis.textContent = `Perfil: ${ponto.perfis.map(rotuloPerfil).join(", ")}`
    container.appendChild(perfis)
  }

  const acoes = document.createElement("div")
  acoes.style.cssText = "margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;"

  if (ponto.bairro && onFiltrarBairro) {
    const botao = document.createElement("button")
    botao.type = "button"
    botao.textContent = "Filtrar bairro"
    botao.style.cssText =
      "padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; background: #1a1a1a; color: #fff; border: 0; border-radius: 4px;"
    botao.addEventListener("click", () => onFiltrarBairro(ponto.bairro!))
    acoes.appendChild(botao)
  }

  // Link "Ver ficha" (MAPA-5): destino /clientes?cliente=<id> destravado pela MAPA-5b.
  // cliente_id é UUID validado pelo backend; encodeURIComponent é defesa em profundidade.
  const ficha = document.createElement("a")
  ficha.href = `/clientes?cliente=${encodeURIComponent(ponto.cliente_id)}`
  ficha.textContent = "Ver ficha"
  ficha.style.cssText = "font-size: 12px; color: #1a1a1a; text-decoration: underline;"
  acoes.appendChild(ficha)

  container.appendChild(acoes)

  return container
}

function formatarDataBR(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" })
}

// InfoWindow do favo Hexbin (MAPA-6): só agregado da célula, sem link de ficha
// (favo agrega N clientes — não há "o cliente" para apontar).
function conteudoFavo(
  info: import("@/lib/deckMap").HexbinPickedInfo,
  metrica: MapaMetrica,
): HTMLElement {
  const container = document.createElement("div")
  container.style.cssText = "font-family: inherit; min-width: 200px; color: #1a1a1a;"

  const titulo = document.createElement("div")
  titulo.style.cssText = "font-weight: 600; margin-bottom: 2px;"
  titulo.textContent = `${info.count} cliente${info.count === 1 ? "" : "s"} nesta área`
  container.appendChild(titulo)

  const linha = document.createElement("div")
  linha.style.cssText = "margin-top: 4px; font-size: 12px; color: #444;"
  linha.textContent = resumoFavo(info, metrica)
  container.appendChild(linha)

  return container
}

function resumoFavo(
  info: import("@/lib/deckMap").HexbinPickedInfo,
  metrica: MapaMetrica,
): string {
  const plural = info.somaAtendimentos === 1 ? "atendimento" : "atendimentos"
  if (metrica === "valor") {
    return `${formatBRL(info.somaValor)} · ${info.somaAtendimentos} ${plural}`
  }
  if (metrica === "atendimentos") {
    return `${info.somaAtendimentos} ${plural} · ${formatBRL(info.somaValor)}`
  }
  return `${info.count} cliente${info.count === 1 ? "" : "s"} · ${info.somaAtendimentos} ${plural}`
}
