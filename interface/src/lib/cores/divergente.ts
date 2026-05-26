// Paleta divergente para o modo Comparar do Mapa de clientes (MAPA-14).
//
// Diferente da rampa sequencial `--seq-*` (que vai do escuro ao dourado para
// "mais ou menos da mesma coisa"), a paleta divergente codifica sinal: um polo
// para "caiu", neutro no meio e outro polo para "subiu". Usada pelo HexagonLayer
// quando `comparar=true` para pintar cada favo pelo delta `metrica(B) − metrica(A)`.
//
// Escolha: BrBG (ColorBrewer) invertida — marrom = caiu, teal/verde-azulado =
// subiu, creme = neutro. Vermelho/verde puros foram descartados por
// acessibilidade (daltonismo deuteranopia/protanopia confunde os dois).
//
// Sem dep nova (sem chroma.js, sem d3-scale-chromatic) — 7 stops literais
// bastam para deck.gl `colorRange` (que interpola entre stops automaticamente)
// e para a legenda CSS (`linear-gradient`).

/** 7 stops da BrBG invertida — marrom escuro → creme → teal escuro. Tuplas RGB
 *  (0..255) no formato que deck.gl `colorRange` espera. Ordem do mais negativo
 *  (delta < 0, "caiu") para o mais positivo (delta > 0, "subiu"). */
export const RAMPA_DIVERGENTE_RGB: ReadonlyArray<[number, number, number]> = [
  [84, 48, 5], // mais negativo — marrom muito escuro
  [191, 129, 45], // negativo — marrom
  [223, 194, 125], // pouco negativo — bege
  [245, 245, 220], // neutro — creme (delta ~0)
  [128, 205, 193], // pouco positivo — teal claro
  [53, 151, 143], // positivo — teal
  [1, 102, 94], // mais positivo — teal muito escuro
] as const

/** Mesmas cores em CSS hex — usadas pela legenda (gradient + dots). */
export const RAMPA_DIVERGENTE_CSS: readonly string[] = [
  "#543005",
  "#BF812D",
  "#DFC27D",
  "#F5F5DC",
  "#80CDC1",
  "#35978F",
  "#01665E",
] as const
