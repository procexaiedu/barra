import type { CorCabelo, CorPele } from "@/tipos/modelos"

/** Ficha cadastral (ADR 0007). Slug ASCII (banco) → rótulo acentuado (UI). */

export const CORES_PELE: CorPele[] = ["branca", "parda", "negra", "asiatica", "indigena", "outra"]

export const COR_PELE_LABEL: Record<CorPele, string> = {
  branca: "Branca",
  parda: "Parda",
  negra: "Negra",
  asiatica: "Asiática",
  indigena: "Indígena",
  outra: "Outra",
}

export const CORES_CABELO: CorCabelo[] = [
  "loiro",
  "castanho_claro",
  "castanho_escuro",
  "preto",
  "ruivo",
  "grisalho",
  "colorido",
  "outra",
]

export const COR_CABELO_LABEL: Record<CorCabelo, string> = {
  loiro: "Loiro",
  castanho_claro: "Castanho claro",
  castanho_escuro: "Castanho escuro",
  preto: "Preto",
  ruivo: "Ruivo",
  grisalho: "Grisalho",
  colorido: "Colorido",
  outra: "Outra",
}
