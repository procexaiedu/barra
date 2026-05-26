import { importLibrary, setOptions } from "@googlemaps/js-api-loader"

// Loader único do Google Maps JS (reusa @googlemaps/js-api-loader, já usado pelo
// autocomplete em CampoLocalAutocomplete). Carrega bibliotecas sob demanda e em cache.
// `setOptions` pode já ter sido chamado pelo autocomplete no mesmo processo (SPA): os
// params são idênticos, então um segundo set é inofensivo — protegido por flag + try.
export const googleMapsApiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? ""

let configurado = false
const bibliotecas = new Map<string, Promise<unknown>>()

function configurar() {
  if (!googleMapsApiKey) throw new Error("missing_api_key")
  if (configurado) return
  try {
    setOptions({ key: googleMapsApiKey, v: "weekly", language: "pt-BR", region: "BR" })
  } catch {
    // Já configurado por outro módulo — importLibrary reaproveita os params globais.
  }
  configurado = true
}

export function carregarBiblioteca<T>(nome: "maps" | "marker" | "places"): Promise<T> {
  configurar()
  let promessa = bibliotecas.get(nome)
  if (!promessa) {
    promessa = importLibrary(nome)
    bibliotecas.set(nome, promessa)
  }
  return promessa as Promise<T>
}
