"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarkerClusterer } from "@googlemaps/markerclusterer"
import { carregarBiblioteca, googleMapsApiKey, googleMapsMapId } from "@/lib/googleMaps"
import { formatBRL } from "@/lib/formatters"
import type { MapaMetrica } from "@/lib/mapaMetrica"
import { LegendaEscala, SeletorMetrica } from "@/components/clientes/MapaControles"
import type { MapaClientePonto } from "@/tipos/clientes"

// Centro aproximado do Brasil para a abertura, antes do fit nos pins (ADR 0008).
const CENTRO_BRASIL = { lat: -14.235, lng: -51.925 }

type Status = "idle" | "loading" | "success" | "error"

export function MapaClientes({
  pontos,
  totalSemLocalizacao,
  status,
  error,
  onRetry,
}: {
  pontos: MapaClientePonto[]
  totalSemLocalizacao: number
  status: Status
  error: string | null
  onRetry: () => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<google.maps.Map | null>(null)
  const infoRef = useRef<google.maps.InfoWindow | null>(null)
  const clustererRef = useRef<MarkerClusterer | null>(null)
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([])
  const [mapPronto, setMapPronto] = useState(false)
  // Métrica do mapa (MAPA-1, espinha dorsal). Default = R$ fechado, conforme spec.
  // Mora aqui porque o único consumidor hoje é o próprio desenho do mapa (e a legenda);
  // sobe para o page.tsx quando MAPA-4 (ranking sibling) chegar.
  const [metrica, setMetrica] = useState<MapaMetrica>("valor")

  // Redesenha os marcadores a partir dos pontos atuais (puro side-effect imperativo no mapa).
  const desenharPontos = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    clustererRef.current?.clearMarkers()
    markersRef.current.forEach((marker) => {
      marker.map = null
    })
    markersRef.current = []

    const bounds = new google.maps.LatLngBounds()
    for (const ponto of pontos) {
      const posicao = { lat: ponto.latitude, lng: ponto.longitude }
      const marker = new google.maps.marker.AdvancedMarkerElement({
        position: posicao,
        title: ponto.nome ?? "Cliente",
        gmpClickable: true,
      })
      // AdvancedMarkerElement usa "gmp-click" (o "click" do Marker legado foi aposentado aqui).
      marker.addListener("gmp-click", () => {
        const info = infoRef.current
        if (!info) return
        info.setContent(conteudoInfo(ponto))
        info.open({ map, anchor: marker })
      })
      markersRef.current.push(marker)
      bounds.extend(posicao)
    }

    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({ map, markers: markersRef.current })
    } else {
      clustererRef.current.addMarkers(markersRef.current)
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
  }, [pontos])

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
        <SeletorMetrica metrica={metrica} onMetricaChange={setMetrica} />
      </div>
      <div className="relative h-[calc(100vh-300px)] min-h-[420px] overflow-hidden rounded-lg border border-border">
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
    </div>
  )
}

// InfoWindow é renderizada pelo Google num balão branco — cores fixas legíveis ali, não
// as do tema escuro do painel. Conteúdo escapado por vir de dado livre (nome/bairro).
function conteudoInfo(ponto: MapaClientePonto): string {
  const nome = escaparHtml(ponto.nome ?? "Cliente")
  const local = escaparHtml(ponto.bairro ?? ponto.endereco_formatado ?? "—")
  const valor = formatBRL(Number(ponto.valor_total))
  const plural = ponto.total_atendimentos === 1 ? "atendimento" : "atendimentos"
  return `
    <div style="font-family: inherit; min-width: 180px; color: #1a1a1a;">
      <div style="font-weight: 600; margin-bottom: 2px;">${nome}</div>
      <div style="color: #666; font-size: 12px;">${local}</div>
      <div style="margin-top: 6px; font-size: 12px;">${ponto.total_atendimentos} ${plural} · ${valor}</div>
    </div>`
}

function escaparHtml(texto: string): string {
  return texto.replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  )
}
