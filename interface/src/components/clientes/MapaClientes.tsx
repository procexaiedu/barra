"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { MarkerClusterer } from "@googlemaps/markerclusterer"
import { carregarBiblioteca, googleMapsApiKey, googleMapsMapId } from "@/lib/googleMaps"
import { formatBRL } from "@/lib/formatters"
import {
  RAMPA_INTENSIDADE_CSS,
  corPinIntensidade,
  limitesMetrica,
  normalizarPeso,
  pesoPonto,
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
  COR_OPORTUNIDADE,
  COR_PERFIL,
  COR_PERFIL_SEM,
  LegendaDelta,
  LegendaDemandaNaoAtendida,
  LegendaDesfecho,
  LegendaEscala,
  LegendaPerfil,
  corPorDesfecho,
  type CompararRecortes,
  type FiltroDesfecho,
  type FiltroRecencia,
  type ModoCor,
} from "@/components/clientes/MapaControles"
import { MapaRanking, chaveBairro } from "@/components/clientes/MapaRanking"
import { Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useIsMobile } from "@/hooks/useMediaQuery"
import { ListTree } from "lucide-react"
import { MapaToolbar } from "@/components/clientes/MapaToolbar"
import { PainelVisualizacaoMapa } from "@/components/clientes/PainelVisualizacaoMapa"
import { RAMPA_FAVO_CSS } from "@/lib/cores/favo"
import { rotuloPerfil } from "@/lib/perfilFisico"
import { emitirContrato } from "@/lib/verify/contract"
import type {
  EstadoAtendimento,
  FiltroPeriodo,
  MapaClientePonto,
  MotivoPerda,
  PerfilFisico,
} from "@/tipos/clientes"

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
  desfecho,
  motivosPerda,
  onDesfechoChange,
  onMotivosPerdaChange,
  lenteDemanda,
  onLenteDemandaChange,
  valorMin,
  valorMax,
  recencia,
  onValorRangeChange,
  onRecenciaChange,
  periodo,
  dataInicio,
  dataFim,
  modeloIds,
  perfis,
  incluirArquivados,
  onPeriodoChange,
  onCustomPeriodoChange,
  onModeloChange,
  onPerfisChange,
  onIncluirArquivadosChange,
  comparar,
  onCompararChange,
}: {
  pontos: MapaClientePonto[]
  totalSemLocalizacao: number
  status: Status
  error: string | null
  onRetry: () => void
  /** MAPA-12: liga o mapa à Lista — informa o bairro do ponto clicado ao pai. */
  onFiltrarBairro?: (bairro: string) => void
  /** MAPA-8: filtros do mapa (vivem no pai porque o hook precisa deles na querystring). */
  desfecho: FiltroDesfecho
  motivosPerda: MotivoPerda[]
  onDesfechoChange: (d: FiltroDesfecho) => void
  onMotivosPerdaChange: (m: MotivoPerda[]) => void
  /** MAPA-9: lente "Demanda não atendida". Quando ON, o fetch já vem reduzido aos
   *  Perdidos por indisponibilidade/fora_de_area e os pontos recebem halo. */
  lenteDemanda: boolean
  onLenteDemandaChange: (v: boolean) => void
  /** MAPA-11: ortogonais ao MAPA-8 e à lente MAPA-9 (sempre aplicados no fetch). */
  valorMin: number | null
  valorMax: number | null
  recencia: FiltroRecencia
  onValorRangeChange: (range: { valorMin: number | null; valorMax: number | null }) => void
  onRecenciaChange: (r: FiltroRecencia) => void
  /** Filtros compartilhados (antes vinham do Toolbar superior). Toolbar some na aba
   *  Mapa — os filtros agora vivem aqui dentro via MapaToolbar/PopoverFiltrosMapa. */
  periodo: FiltroPeriodo
  /** Task 9: janela do "Período personalizado" (ISO `YYYY-MM-DD`). */
  dataInicio: string | null
  dataFim: string | null
  modeloIds: string[]
  perfis: PerfilFisico[]
  incluirArquivados: boolean
  onPeriodoChange: (v: FiltroPeriodo) => void
  onCustomPeriodoChange: (range: { dataInicio: string | null; dataFim: string | null }) => void
  onModeloChange: (v: string[]) => void
  onPerfisChange: (v: PerfilFisico[]) => void
  onIncluirArquivadosChange: (v: boolean) => void
  /** MAPA-14: modo Comparar dois períodos (lift de campanha). Quando ativo +
   *  ranges válidos, força camada Hexbin com paleta divergente e InfoWindow
   *  A/B/delta no clique do favo. */
  comparar: CompararRecortes
  onCompararChange: (next: CompararRecortes) => void
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
  const isMobile = useIsMobile()
  // Mobile: ranking de bairros vai para um Sheet (o mapa fica em tela cheia).
  const [rankingAberto, setRankingAberto] = useState(false)
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

  // MAPA-14: o modo Comparar está "ativo" quando o toggle está ON E os dois
  // recortes têm fim >= início. Antes de a UI preencher as datas, o hook
  // também segura o fetch — defesa em profundidade.
  const compararAtivo =
    comparar.comparar &&
    comparar.aInicio !== null &&
    comparar.aFim !== null &&
    comparar.bInicio !== null &&
    comparar.bFim !== null &&
    comparar.aInicio <= comparar.aFim &&
    comparar.bInicio <= comparar.bFim

  // MAPA-14: no modo Comparar a camada efetiva é Hexbin (única honesta para
  // delta espacial — bolhas é ponto-a-ponto, KDE com delta hiperestima). Não
  // muta `camada` (estado do usuário): só sobrescreve aqui. Desligar Comparar
  // devolve a escolha anterior naturalmente.
  const camadaEfetiva: MapaCamada = compararAtivo ? "hexbin" : camada

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
    // deck.gl renderiza — markers/cluster ficam ocultos. `camadaEfetiva` força
    // hexbin no modo Comparar mesmo se o estado do usuário for outro (MAPA-14).
    if (camadaEfetiva !== "bolhas") return

    const limites = limitesMetrica(pontos, metrica)
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    for (const ponto of pontos) {
      const posicao = { lat: ponto.latitude, lng: ponto.longitude }
      const peso = normalizarPeso(pesoPonto(ponto, metrica), limites)
      const content = conteudoPorModo(modoCor, ponto, peso, lenteDemanda)
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
  }, [pontos, onFiltrarBairro, modoCor, metrica, camadaEfetiva, lenteDemanda])

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
  // desfecho/perfil ou bolha sqrt-escalada) ao deselecionar. `lenteDemanda` entra
  // nas deps para reaplicar o halo de oportunidade (MAPA-9) ao alternar a lente.
  useEffect(() => {
    aplicarDestaque(markersRef.current, bairroSelecionado, modoCor, lenteDemanda)
  }, [bairroSelecionado, mapPronto, pontos, modoCor, lenteDemanda])

  // MAPA-6: ciclo de vida do overlay deck.gl. Cria ao entrar em "hexbin"
  // (import dinâmico), atualiza quando pontos/métrica mudam, descarta ao sair.
  // O sequencial evita aplicar um overlay obsoleto se a camada virar antes do
  // import resolver (alternância rápida).
  useEffect(() => {
    if (!mapPronto) return
    const map = mapRef.current
    if (!map) return
    if (camadaEfetiva !== "hexbin") {
      hexbinRef.current?.dispose()
      hexbinRef.current = null
      return
    }
    const opts = {
      pontos,
      metrica,
      // MAPA-14: passa o flag ao overlay para alternar entre rampa sequencial
      // (sum por célula) e rampa divergente (delta B − A).
      comparar: compararAtivo,
      onClickFavo: (info: import("@/lib/deckMap").HexbinPickedInfo) => {
        const win = infoRef.current
        if (!win) return
        win.setContent(conteudoFavo(info, metrica, compararAtivo))
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
  }, [camadaEfetiva, pontos, metrica, mapPronto, compararAtivo])

  // MAPA-7: ciclo de vida do overlay deck.gl Calor (HeatmapLayer KDE). Espelha
  // o do hexbin — diferença é que não há picking (campo contínuo). O guard de
  // honestidade (limiar mínimo de pontos) vive no SeletorCamada, que desabilita
  // o botão; se mesmo assim a camada for "calor" sem volume suficiente, o
  // overlay sobe e renderiza um borrão fraco — não é erro, é só feio.
  useEffect(() => {
    if (!mapPronto) return
    const map = mapRef.current
    if (!map) return
    // SeletorCamada bloqueia *entrar* em "calor" com < LIMIAR_CALOR_MIN_PONTOS,
    // mas filtros agressivos podem zerar `pontos` JÁ DENTRO da camada — sem
    // este guard, paga import dinâmico + criação de overlay vazio em vão.
    if (camadaEfetiva !== "calor" || pontos.length === 0) {
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
  }, [camadaEfetiva, pontos, metrica, mapPronto])

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
    <div
      {...emitirContrato("mapa", {
        pins: pontos.length,
        semLocalizacao: totalSemLocalizacao,
        totalClientes: pontos.length + totalSemLocalizacao,
      })}
      className="space-y-3"
    >
      <MapaToolbar
        periodo={periodo}
        dataInicio={dataInicio}
        dataFim={dataFim}
        modeloIds={modeloIds}
        perfis={perfis}
        desfecho={desfecho}
        motivosPerda={motivosPerda}
        valorMin={valorMin}
        valorMax={valorMax}
        recencia={recencia}
        incluirArquivados={incluirArquivados}
        lenteDemanda={lenteDemanda}
        comparar={comparar}
        totalNoMapa={pontos.length}
        totalSemLocalizacao={totalSemLocalizacao}
        onPeriodoChange={onPeriodoChange}
        onCustomPeriodoChange={onCustomPeriodoChange}
        onModeloChange={onModeloChange}
        onPerfisChange={onPerfisChange}
        onDesfechoChange={onDesfechoChange}
        onMotivosPerdaChange={onMotivosPerdaChange}
        onValorRangeChange={onValorRangeChange}
        onRecenciaChange={onRecenciaChange}
        onIncluirArquivadosChange={onIncluirArquivadosChange}
        onLenteDemandaChange={onLenteDemandaChange}
        onCompararChange={onCompararChange}
      />
      <div className="flex h-[60vh] min-h-[360px] gap-2 lg:h-[calc(100vh-300px)] lg:min-h-[420px]">
        <div className="relative flex-1 overflow-hidden rounded-lg border border-border">
          <div ref={containerRef} className="h-full w-full" />
          {isMobile && (
            <button
              type="button"
              onClick={() => setRankingAberto(true)}
              className="absolute bottom-3 right-3 z-10 inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-2 text-xs font-medium text-text-primary shadow-md transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ListTree size={15} strokeWidth={1.5} />
              Ranking
            </button>
          )}
          {/* Painel de Visualização (Camada/Métrica/Cor) flutua dentro do mapa,
              perto dos pontos que pinta — ortogonal aos filtros (que reduzem o conjunto). */}
          <div className="absolute right-3 top-3">
            <PainelVisualizacaoMapa
              camada={camada}
              pontosCount={pontos.length}
              metrica={metrica}
              modoCor={modoCor}
              comparar={compararAtivo}
              onCamadaChange={setCamada}
              onMetricaChange={setMetrica}
              onModoCorChange={setModoCor}
            />
          </div>
          <div className="absolute bottom-3 left-3 flex flex-col gap-2">
            {/* Legenda contextual: só aparece o que realmente codifica algo no mapa.
                - MAPA-14 ON → rampa divergente (LegendaDelta), independente da camada.
                - Pontos+Por métrica → rampa de intensidade (→ vermelho), casa com o pin (Task 12).
                - Hexbin/Calor → rampa --seq-* (LegendaEscala, default).
                - Pontos+Por desfecho → 3 baldes de cor (LegendaDesfecho).
                - Pontos+Por perfil → 6 categorias + Sem declaração (LegendaPerfil).
                Em todos os outros (camada ≠ Pontos), a cor é sempre da métrica. */}
            {compararAtivo ? (
              <LegendaDelta metrica={metrica} />
            ) : camadaEfetiva === "bolhas" && modoCor === "desfecho" ? (
              <LegendaDesfecho />
            ) : camadaEfetiva === "bolhas" && modoCor === "perfil" ? (
              <LegendaPerfil />
            ) : (
              <LegendaEscala
                metrica={metrica}
                pontos={pontos}
                // Task 12: Pontos+Métrica usa a rampa de intensidade (→ vermelho no
                // mais quente), casando com a cor do pin. Hexbin usa a rampa de favo
                // (refino visual). Calor/default seguem na rampa --seq-*.
                rampa={
                  camadaEfetiva === "bolhas" && modoCor === "metrica"
                    ? RAMPA_INTENSIDADE_CSS
                    : camadaEfetiva === "hexbin"
                      ? RAMPA_FAVO_CSS
                      : undefined
                }
              />
            )}
            {/* MAPA-9: enquanto a lente está ON, explica o subset visualmente independente
                da camada/modo de cor — em Hexbin/Calor essa é a ÚNICA pista visual da lente
                (favos/heatmap renderizam sobre o subset reduzido, sem halo por-favo). */}
            {lenteDemanda && <LegendaDemandaNaoAtendida />}
          </div>
          {status === "loading" && pontos.length === 0 && (
            <div className="absolute inset-0 grid place-items-center text-sm text-text-muted">
              Buscando clientes…
            </div>
          )}
          {status === "error" && (
            <div className="absolute inset-0 grid place-items-center gap-2 bg-card/80 text-sm text-state-lost">
              <span>{error ?? "Não foi possível carregar o mapa."}</span>
              <button type="button" onClick={onRetry} className="underline underline-offset-2">
                Tentar de novo
              </button>
            </div>
          )}
          {status === "success" && pontos.length === 0 && (
            <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-text-muted">
              Nenhum cliente nos filtros atuais. O mapa só mostra clientes com endereço cadastrado
              em algum atendimento externo.
            </div>
          )}
        </div>
        {!isMobile && (
          <MapaRanking
            pontos={pontos}
            metrica={metrica}
            onSelectBairro={handleSelectBairro}
          />
        )}
      </div>

      {isMobile && (
        <Sheet open={rankingAberto} onOpenChange={setRankingAberto}>
          <SheetContent side="bottom" className="max-h-[70vh]">
            <SheetHeader>
              <SheetTitle>Top bairros</SheetTitle>
            </SheetHeader>
            <SheetBody className="p-3">
              <MapaRanking
                className="h-auto max-h-[55vh] w-full border-0"
                pontos={pontos}
                metrica={metrica}
                onSelectBairro={(chave) => {
                  handleSelectBairro(chave)
                  setRankingAberto(false)
                }}
              />
            </SheetBody>
          </SheetContent>
        </Sheet>
      )}
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

// Task 12 — marcador em formato de PIN/SETA (gota) colorido por INTENSIDADE da
// métrica (cliente mais "quente" = vermelho, decisão do cliente). Substitui a
// bolha circular do MAPA-2 no modo "Por métrica". O SVG é desenhado com a PONTA
// no bottom-center do viewBox; como o AdvancedMarker ancora o `content` pelo
// bottom-center, a ponta cai exatamente sobre a coordenada (sem `translateY`).
//
// Tamanho cresce levemente com a intensidade (sqrt → área proporcional, como a
// bolha), mas em faixa mais estreita: pin grande demais polui o mapa e esconde
// vizinhos. Cor vem de `corPinIntensidade` (rampa sequencial → vermelho no topo).
const PIN_ALTURA_MIN_PX = 30
const PIN_ALTURA_MAX_PX = 46

function criarConteudoPin(peso: number): HTMLElement {
  const altura = PIN_ALTURA_MIN_PX + (PIN_ALTURA_MAX_PX - PIN_ALTURA_MIN_PX) * Math.sqrt(peso)
  // Proporção fixa da gota (largura ≈ 0.72 da altura) para a forma não distorcer.
  const largura = altura * 0.72
  const cor = corPinIntensidade(peso)
  const SVG_NS = "http://www.w3.org/2000/svg"
  const svg = document.createElementNS(SVG_NS, "svg")
  svg.setAttribute("width", String(largura))
  svg.setAttribute("height", String(altura))
  svg.setAttribute("viewBox", "0 0 24 32")
  svg.style.cssText = "display:block;cursor:pointer;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.4));"
  // Gota clássica: cabeça circular em cima, ponta no bottom-center (12,32).
  const path = document.createElementNS(SVG_NS, "path")
  path.setAttribute(
    "d",
    "M12 0C5.92 0 1 4.92 1 11c0 7.7 9.1 19.2 10.06 20.4a1.2 1.2 0 0 0 1.88 0C13.9 30.2 23 18.7 23 11 23 4.92 18.08 0 12 0z",
  )
  path.setAttribute("fill", cor)
  path.setAttribute("stroke", "rgba(255,255,255,0.92)")
  path.setAttribute("stroke-width", "1.5")
  svg.appendChild(path)
  // Furo branco no centro da cabeça — dá leitura de "pin" e contraste em qualquer cor.
  const furo = document.createElementNS(SVG_NS, "circle")
  furo.setAttribute("cx", "12")
  furo.setAttribute("cy", "11")
  furo.setAttribute("r", "3.6")
  furo.setAttribute("fill", "rgba(255,255,255,0.92)")
  svg.appendChild(furo)
  // Wrapper para o AdvancedMarker (ancora o elemento, não o SVG raw) e para o
  // bindClickAoContent anexar o handler no nó-content.
  const el = document.createElement("div")
  el.style.cssText = "display:block;line-height:0;cursor:pointer;"
  el.appendChild(svg)
  return el
}

function conteudoPorModo(
  modoCor: ModoCor,
  ponto: MapaClientePonto,
  peso: number,
  lenteDemanda: boolean,
): HTMLElement {
  let base: HTMLElement
  let kind: "bolha" | "pin"
  if (modoCor === "desfecho") {
    base = criarConteudoDesfecho(ponto.estado)
    kind = "pin"
  } else if (modoCor === "perfil") {
    base = criarConteudoPerfil(ponto.perfis)
    kind = "pin"
  } else {
    // modoCor === "metrica" (Task 12): pin/seta sqrt-escalado, cor por intensidade
    // (rampa sequencial → vermelho no mais quente).
    base = criarConteudoPin(peso)
    kind = "pin"
  }
  return lenteDemanda ? envolverComHaloOportunidade(base, kind) : base
}

/** MAPA-9: aplica o halo de "oportunidade" ao content do AdvancedMarkerElement.
 *  - "bolha"/"disco" (div circular): anel via box-shadow concêntrico — preserva
 *    o transform/anchoring existente sem precisar de wrapper. O `border-radius:50%`
 *    do próprio div faz o box-shadow ficar circular.
 *  - "pin" (PinElement, SVG-gota): wrapper relative com SVG halo absoluto centrado
 *    na cabeça do pin. `pointer-events: none` no wrapper+SVG garante que cliques
 *    ainda cheguem ao content original (handler do bindClickAoContent). */
function envolverComHaloOportunidade(
  inner: HTMLElement,
  kind: "bolha" | "pin",
): HTMLElement {
  if (kind === "bolha") {
    const prev = inner.style.boxShadow
    inner.style.boxShadow = `${prev ? prev + ", " : ""}0 0 0 2px ${COR_OPORTUNIDADE}`
    return inner
  }
  const SVG_NS = "http://www.w3.org/2000/svg"
  const wrap = document.createElement("div")
  // pointer-events:none deixa cliques na área externa ao content passarem direto
  // pro mapa (sem bloquear pan/zoom). O content filho herda `auto` por default.
  wrap.style.cssText =
    "position: relative; display: inline-block; pointer-events: none;"
  const svg = document.createElementNS(SVG_NS, "svg")
  svg.setAttribute("width", "34")
  svg.setAttribute("height", "34")
  svg.setAttribute("viewBox", "0 0 34 34")
  // PinElement padrão ~27x40, cabeça arredondada centrada horizontalmente. Posicionamos
  // o halo sobre a cabeça (não a ponta) — `top: -2px` cobre folga sutil.
  svg.style.cssText =
    "position: absolute; left: 50%; top: -2px; transform: translateX(-50%); pointer-events: none;"
  const circle = document.createElementNS(SVG_NS, "circle")
  circle.setAttribute("cx", "17")
  circle.setAttribute("cy", "17")
  circle.setAttribute("r", "16")
  circle.setAttribute("fill", "none")
  circle.setAttribute("stroke", COR_OPORTUNIDADE)
  circle.setAttribute("stroke-width", "1.5")
  svg.appendChild(circle)
  wrap.appendChild(svg)
  wrap.appendChild(inner)
  return wrap
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
  lenteDemanda: boolean,
) {
  for (const { marker, chave, estado, perfis, peso, abrirInfo } of items) {
    let novo: HTMLElement
    let kind: "bolha" | "pin"
    if (selecionado && chave === selecionado) {
      // Disco dourado do MAPA-4 também é circular — mesmo trato da bolha.
      novo = criarConteudoDestaque()
      kind = "bolha"
    } else if (modoCor === "desfecho") {
      novo = criarConteudoDesfecho(estado)
      kind = "pin"
    } else if (modoCor === "perfil") {
      novo = criarConteudoPerfil(perfis)
      kind = "pin"
    } else {
      // modoCor === "metrica" (Task 12): pin/seta colorido por intensidade.
      novo = criarConteudoPin(peso)
      kind = "pin"
    }
    // MAPA-9: halo de oportunidade convive com o destaque MAPA-4 (bairro selecionado
    // continua sinalizado pela cor dourada; o halo magenta indica a lente).
    const conteudo = lenteDemanda ? envolverComHaloOportunidade(novo, kind) : novo
    marker.content = conteudo
    // Re-bind do click no content original (não no wrapper) — handler segue no
    // elemento alvo do clique; o wrapper tem pointer-events:none.
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
    ponto.recorrente === undefined
      ? "—"
      : ponto.recorrente
        ? "Cliente recorrente"
        : "Veio só uma vez"
  const meta = document.createElement("div")
  meta.style.cssText = "margin-top: 2px; font-size: 12px; color: #666;"
  meta.textContent = `Atendido em ${ultima} · ${recorrencia}`
  container.appendChild(meta)

  // Perfil físico DECLARADO (MAPA-10, ADR 0006). Lista todos quando >1 — o pin pega
  // só o primeiro como cor. Sem declaração, omite a linha (não confunde com "outra").
  if (ponto.perfis.length > 0) {
    const perfis = document.createElement("div")
    perfis.style.cssText = "margin-top: 4px; font-size: 12px; color: #666;"
    perfis.textContent = `Perfil físico: ${ponto.perfis.map(rotuloPerfil).join(", ")}`
    container.appendChild(perfis)
  }

  const acoes = document.createElement("div")
  acoes.style.cssText = "margin-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;"

  if (ponto.bairro && onFiltrarBairro) {
    const botao = document.createElement("button")
    botao.type = "button"
    botao.textContent = "Ver só este bairro"
    botao.style.cssText =
      "padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; background: #1a1a1a; color: #fff; border: 0; border-radius: 4px;"
    botao.addEventListener("click", () => onFiltrarBairro(ponto.bairro!))
    acoes.appendChild(botao)
  }

  // Link "Ver ficha" (MAPA-5): destino /clientes?cliente=<id> destravado pela MAPA-5b.
  // cliente_id é UUID validado pelo backend; encodeURIComponent é defesa em profundidade.
  const ficha = document.createElement("a")
  ficha.href = `/clientes?cliente=${encodeURIComponent(ponto.cliente_id)}`
  ficha.textContent = "Abrir ficha"
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
// MAPA-14: quando `comparar=true` o card mostra `A`, `B` e `delta = B − A` da
// métrica corrente — A/B já vêm calculados em `info.somaA`/`somaB`/`delta`.
function conteudoFavo(
  info: import("@/lib/deckMap").HexbinPickedInfo,
  metrica: MapaMetrica,
  comparar: boolean,
): HTMLElement {
  const container = document.createElement("div")
  container.style.cssText = "font-family: inherit; min-width: 220px; color: #1a1a1a;"

  const titulo = document.createElement("div")
  titulo.style.cssText = "font-weight: 600; margin-bottom: 2px;"
  titulo.textContent = `${info.count} cliente${info.count === 1 ? "" : "s"} nesta área`
  container.appendChild(titulo)

  if (comparar && info.delta !== undefined) {
    const somaA = info.somaA ?? 0
    const somaB = info.somaB ?? 0
    const delta = info.delta
    const fmt = (n: number) => formatarMetricaFavo(metrica, n)
    const linhaA = document.createElement("div")
    linhaA.style.cssText = "margin-top: 4px; font-size: 12px; color: #444;"
    linhaA.textContent = `Período A: ${fmt(somaA)}`
    container.appendChild(linhaA)
    const linhaB = document.createElement("div")
    linhaB.style.cssText = "font-size: 12px; color: #444;"
    linhaB.textContent = `Período B: ${fmt(somaB)}`
    container.appendChild(linhaB)
    const linhaDelta = document.createElement("div")
    const rotulo = delta > 0 ? "Subiu" : delta < 0 ? "Caiu" : "Sem mudança"
    linhaDelta.style.cssText = `margin-top: 2px; font-size: 12px; font-weight: 600; color: ${
      delta > 0 ? "#01665E" : delta < 0 ? "#543005" : "#444"
    };`
    linhaDelta.textContent =
      delta === 0 ? rotulo : `${rotulo}: ${fmt(Math.abs(delta))}`
    container.appendChild(linhaDelta)
  } else {
    const linha = document.createElement("div")
    linha.style.cssText = "margin-top: 4px; font-size: 12px; color: #444;"
    linha.textContent = resumoFavo(info, metrica)
    container.appendChild(linha)
  }

  return container
}

function formatarMetricaFavo(metrica: MapaMetrica, n: number): string {
  if (metrica === "valor") return formatBRL(n)
  if (metrica === "atendimentos") {
    return `${n} atendimento${n === 1 ? "" : "s"}`
  }
  return `${n} cliente${n === 1 ? "" : "s"}`
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
