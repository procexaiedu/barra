import type { CorCabelo, CorPele, Signo } from "@/tipos/modelos"

/** Ficha cadastral (ADR 0007). Slug ASCII (banco) → rótulo acentuado (UI). */

export const CORES_PELE: CorPele[] = ["branca", "parda", "negra", "asiatica", "outra"]

export const COR_PELE_LABEL: Record<CorPele, string> = {
  branca: "Branca",
  parda: "Parda",
  negra: "Negra",
  asiatica: "Asiática",
  outra: "Outra",
}

export const CORES_CABELO: CorCabelo[] = [
  "loiro",
  "castanho",
  "preto",
  "ruivo",
  "colorido",
  "outro",
]

export const COR_CABELO_LABEL: Record<CorCabelo, string> = {
  loiro: "Loiro",
  castanho: "Castanho",
  preto: "Preto",
  ruivo: "Ruivo",
  colorido: "Colorido",
  outro: "Outro",
}

/** Os 12 signos (seleção manual; não há data_nascimento, só idade). */
export const SIGNOS: Signo[] = [
  "aries",
  "touro",
  "gemeos",
  "cancer",
  "leao",
  "virgem",
  "libra",
  "escorpiao",
  "sagitario",
  "capricornio",
  "aquario",
  "peixes",
]

export const SIGNO_LABEL: Record<Signo, string> = {
  aries: "Áries",
  touro: "Touro",
  gemeos: "Gêmeos",
  cancer: "Câncer",
  leao: "Leão",
  virgem: "Virgem",
  libra: "Libra",
  escorpiao: "Escorpião",
  sagitario: "Sagitário",
  capricornio: "Capricórnio",
  aquario: "Aquário",
  peixes: "Peixes",
}
