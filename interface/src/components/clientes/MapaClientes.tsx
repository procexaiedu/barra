"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarkerClusterer } from "@googlemaps/markerclusterer"
import { carregarBiblioteca, googleMapsApiKey, googleMapsMapId } from "@/lib/googleMaps"
import { formatBRL } from "@/lib/formatters"
import type { MapaMetrica } from "@/lib/mapaMetrica"
import {
  LegendaEscala,
  SeletorMetrica,
  SeletorModoCor,
  type ModoCor,
} from "@/components/clientes/MapaControles"
import { MapaRanking, chaveBairro } from "@/components/clientes/MapaRanking"
import { rotuloPerfil } from "@/lib/perfilFisico"
import type { EstadoAtendimento, MapaClientePonto, PerfilFisico } from "@/tipos/clientes"

// Centro aproximado do Brasil para a abertura, antes do fit nos pins (ADR 0008).
const CENTRO_BRASIL = { lat: -14.235, lng: -51.925 }

// Cores do modo "Por desfecho" (MAPA-3). Hex literal porque PinElement não resolve
// CSS vars; valores espelham --state-closed/--state-lost/--state-handoff do tema.
const COR_FECHADO = "#1FB07A"
const COR_PERDIDO = "#D62828"
const COR_EM_ANDAMENTO = "#F4B81C"

function corPorDesfecho(estado: EstadoAtendimento): string {
  if (estado === "Fechado") return COR_FECHADO
  if (estado === "Perdido") return COR_PERDIDO
  return COR_EM_ANDAMENTO
}

// Paleta categórica do modo "Por perfil físico" (MAPA-10). Hex literal porque
// PinElement não resolve CSS vars; valores espelham --chart-1..6 do tema escuro.
const COR_PERFIL: Record<PerfilFisico, string> = {
  loira: "#C4A961",
  morena: "#4F8FE1",
  ruiva: "#1FB07A",
  negra: "#B66CD9",
  asiatica: "#E07A5F",
  outra: "#6FCFC9",
}
// Sem perfil declarado: cinza neutro, distinto das categorias.
const COR_PERFIL_SEM = "#7A7A7A"

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
  // Marcadores guardam o bairro (destaque MAPA-4), o estado (cor MAPA-3) e os perfis
  // declarados (cor MAPA-10) para que os efeitos re-renderizem sem refazer a varredura.
  const markersRef = useRef<
    Array<{
      marker: google.maps.marker.AdvancedMarkerElement
      chave: string
      estado: EstadoAtendimento
      perfis: PerfilFisico[]
    }>
  >([])
  const [mapPronto, setMapPronto] = useState(false)
  // Métrica do mapa (MAPA-1, espinha dorsal). Default = R$ fechado, conforme spec.
  const [metrica, setMetrica] = useState<MapaMetrica>("valor")
  // MAPA-3: modo de cor dos pontos. Ortogonal à métrica (que rege o tamanho).
  // Default "metrica" preserva o comportamento prévio.
  const [modoCor, setModoCor] = useState<ModoCor>("metrica")
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

    const bounds = new google.maps.LatLngBounds()
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    for (const ponto of pontos) {
      const posicao = { lat: ponto.latitude, lng: ponto.longitude }
      const marker = new google.maps.marker.AdvancedMarkerElement({
        position: posicao,
        title: ponto.nome ?? "Cliente",
        gmpClickable: true,
        content: conteudoPorModo(modoCor, ponto),
      })
      // AdvancedMarkerElement usa "gmp-click" (o "click" do Marker legado foi aposentado aqui).
      marker.addListener("gmp-click", () => {
        const info = infoRef.current
        if (!info) return
        info.setContent(conteudoInfo(ponto, onFiltrarBairro))
        info.open({ map, anchor: marker })
      })
      markersRef.current.push({
        marker,
        chave: chaveBairro(ponto),
        estado: ponto.estado,
        perfis: ponto.perfis,
      })
      markers.push(marker)
      bounds.extend(posicao)
    }

    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({ map, markers })
    } else {
      clustererRef.current.addMarkers(markers)
    }

    if (pontos.length > 0) {
      map.fitBounds(bounds, 64)
      // Um único ponto faz o fitBounds dar zoom máximo; limita para algo navegável.
      if (pontos.length === 1) {
        google.maps.event.addListenerOnce(map, "idle", () => {
          if ((map.getZoom() ?? 0) > 14) map.setZoom(14)
        })
      }
    }
  }, [pontos, onFiltrarBairro, modoCor])

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
        mapRef.current = new Map(containerRef.current, {
          center: CENTRO_BRASIL,
          zoom: 4,
          mapId: googleMapsMapId,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
        })
        infoRef.current = new InfoWindow()
        setMapPronto(true)
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
  // Inclui `modoCor` nas deps para restaurar a cor por desfecho ao deselecionar.
  useEffect(() => {
    aplicarDestaque(markersRef.current, bairroSelecionado, modoCor)
  }, [bairroSelecionado, mapPronto, pontos, modoCor])

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
          <SeletorMetrica metrica={metrica} onMetricaChange={setMetrica} />
          <SeletorModoCor modo={modoCor} onModoChange={setModoCor} />
        </div>
      </div>
      <div className="flex h-[calc(100vh-300px)] min-h-[420px] gap-2">
        <div className="relative flex-1 overflow-hidden rounded-lg border border-border">
          <div ref={containerRef} className="h-full w-full" />
          <div className="absolute bottom-3 left-3">
            <LegendaEscala metrica={metrica} pontos={pontos} />
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

function conteudoPorModo(
  modoCor: ModoCor,
  ponto: MapaClientePonto,
): HTMLElement | null {
  if (modoCor === "desfecho") return criarConteudoDesfecho(ponto.estado)
  if (modoCor === "perfil") return criarConteudoPerfil(ponto.perfis)
  return null
}

// Mutação imperativa de instâncias do Google Maps — isolada aqui (fora do hook)
// porque o React Compiler trata refs como imutáveis no escopo de useEffect.
function aplicarDestaque(
  items: ReadonlyArray<{
    marker: google.maps.marker.AdvancedMarkerElement
    chave: string
    estado: EstadoAtendimento
    perfis: PerfilFisico[]
  }>,
  selecionado: string | null,
  modoCor: ModoCor,
) {
  for (const { marker, chave, estado, perfis } of items) {
    if (selecionado && chave === selecionado) {
      marker.content = criarConteudoDestaque()
    } else if (modoCor === "desfecho") {
      marker.content = criarConteudoDesfecho(estado)
    } else if (modoCor === "perfil") {
      marker.content = criarConteudoPerfil(perfis)
    } else {
      marker.content = null
    }
  }
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

  // Perfil físico DECLARADO (MAPA-10, ADR 0006). Lista todos quando >1 — o pin pega
  // só o primeiro como cor. Sem declaração, omite a linha (não confunde com "outra").
  if (ponto.perfis.length > 0) {
    const perfis = document.createElement("div")
    perfis.style.cssText = "margin-top: 4px; font-size: 12px; color: #666;"
    perfis.textContent = `Perfil: ${ponto.perfis.map(rotuloPerfil).join(", ")}`
    container.appendChild(perfis)
  }

  if (ponto.bairro && onFiltrarBairro) {
    const botao = document.createElement("button")
    botao.type = "button"
    botao.textContent = "Filtrar bairro"
    botao.style.cssText =
      "margin-top: 8px; padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; background: #1a1a1a; color: #fff; border: 0; border-radius: 4px;"
    botao.addEventListener("click", () => onFiltrarBairro(ponto.bairro!))
    container.appendChild(botao)
  }

  return container
}
