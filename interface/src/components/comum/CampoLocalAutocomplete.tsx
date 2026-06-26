"use client"

import { useEffect, useId, useRef, useState } from "react"
import { importLibrary, setOptions } from "@googlemaps/js-api-loader"
import { Input } from "@/components/ui/input"

export interface LocalSelecionado {
  endereco_formatado: string
  nome_local: string | null
  latitude: number
  longitude: number
  place_id: string
  localizacao_curta: string
}

const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? ""

let configurado = false
let placesPromise: Promise<google.maps.PlacesLibrary> | null = null

function carregarPlaces() {
  if (!apiKey) return Promise.reject(new Error("missing_api_key"))
  if (!configurado) {
    setOptions({ key: apiKey, v: "weekly", language: "pt-BR", region: "BR" })
    configurado = true
  }
  if (!placesPromise) {
    placesPromise = importLibrary("places") as Promise<google.maps.PlacesLibrary>
  }
  return placesPromise
}

function bairroCidade(place: google.maps.places.Place): string {
  const componentes = place.addressComponents ?? []
  const buscar = (tipo: string) =>
    componentes.find((c) => c.types?.includes(tipo))?.shortText ??
    componentes.find((c) => c.types?.includes(tipo))?.longText ??
    null
  const bairro = buscar("sublocality") ?? buscar("sublocality_level_1") ?? buscar("neighborhood")
  const cidade = buscar("administrative_area_level_2") ?? buscar("locality")
  return [bairro, cidade].filter(Boolean).join(", ") || (place.formattedAddress ?? "")
}

export function CampoLocalAutocomplete({
  valorInicial,
  enderecoFormatadoAtual,
  onSelecionar,
  onLimpar,
}: {
  valorInicial: string
  enderecoFormatadoAtual: string | null
  onSelecionar: (local: LocalSelecionado) => void
  onLimpar: () => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const elementoRef = useRef<google.maps.places.PlaceAutocompleteElement | null>(null)
  const onSelecionarRef = useRef(onSelecionar)
  const [pronto, setPronto] = useState(false)
  const [erro, setErro] = useState<string | null>(apiKey ? null : "missing_api_key")
  const inputId = useId()

  useEffect(() => {
    onSelecionarRef.current = onSelecionar
  }, [onSelecionar])

  useEffect(() => {
    if (!apiKey) return
    let cancelado = false
    carregarPlaces()
      .then(() => {
        if (cancelado || !containerRef.current) return
        const elemento = new google.maps.places.PlaceAutocompleteElement({
          includedRegionCodes: ["br"],
          requestedLanguage: "pt-BR",
          requestedRegion: "br",
        })
        elemento.id = inputId
        elemento.style.width = "100%"
        elemento.addEventListener("gmp-select", async (event) => {
          const place = event.placePrediction.toPlace()
          try {
            await place.fetchFields({
              fields: ["formattedAddress", "location", "displayName", "addressComponents", "id"],
            })
          } catch (e) {
            setErro(e instanceof Error ? e.message : "falha_detalhes")
            return
          }
          const loc = place.location
          if (!loc || !place.formattedAddress) return
          // displayName é o nome do estabelecimento num POI (ex.: "Hotel Vitória"); num
          // endereço puro ele costuma repetir a rua — aí descartamos pra não duplicar.
          const nome = place.displayName ?? null
          const nomeLocal = nome && !place.formattedAddress.startsWith(nome) ? nome : null
          onSelecionarRef.current({
            endereco_formatado: place.formattedAddress,
            nome_local: nomeLocal,
            latitude: loc.lat(),
            longitude: loc.lng(),
            place_id: place.id,
            localizacao_curta: bairroCidade(place),
          })
        })
        elemento.addEventListener("gmp-error", () => setErro("falha_autocomplete"))
        containerRef.current.appendChild(elemento)
        elementoRef.current = elemento
        setPronto(true)
      })
      .catch((e: Error) => setErro(e.message || "falha_carregar"))
    return () => {
      cancelado = true
      elementoRef.current?.remove()
      elementoRef.current = null
    }
  }, [inputId])

  useEffect(() => {
    if (elementoRef.current && enderecoFormatadoAtual !== null) {
      elementoRef.current.value = enderecoFormatadoAtual
    }
  }, [enderecoFormatadoAtual, pronto])

  if (!apiKey || erro === "missing_api_key") {
    return (
      <div className="grid gap-1">
        <Input
          value={valorInicial}
          onChange={(e) => {
            const texto = e.target.value
            if (texto.trim().length === 0) onLimpar()
          }}
          placeholder="Bairro, cidade — chave Google Maps não configurada"
          className="h-10 bg-input"
        />
        <p className="text-[11px] normal-case tracking-normal text-text-muted">
          Configure NEXT_PUBLIC_GOOGLE_MAPS_API_KEY para habilitar o autocomplete.
        </p>
      </div>
    )
  }

  return (
    <div className="grid gap-1">
      <div ref={containerRef} className="min-h-10" />
      {!pronto && !erro && (
        <p className="text-[11px] normal-case tracking-normal text-text-muted">Carregando autocomplete…</p>
      )}
      {erro && erro !== "missing_api_key" && (
        <p className="text-[11px] normal-case tracking-normal text-state-lost">Falha no autocomplete ({erro}).</p>
      )}
      {enderecoFormatadoAtual && (
        <button
          type="button"
          onClick={() => {
            if (elementoRef.current) elementoRef.current.value = ""
            onLimpar()
          }}
          className="justify-self-start text-[11px] normal-case tracking-normal text-text-muted underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-sm"
        >
          Limpar endereço
        </button>
      )}
    </div>
  )
}
