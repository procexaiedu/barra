// Rampa sequencial dos Favos (Hexbin) do Mapa de clientes.
//
// Diferente da rampa `--seq-*` do tema (que vai do quase-preto #1A1606 ao
// dourado), o favo precisa de um degrau BAIXO claro: cada célula é pintada com
// 100% de cobertura, então um fim escuro vira "buraco"/tile faltando sobre o
// mapa claro e quebra a metáfora "mais quente = mais valor". Aqui a rampa vai do
// dourado PÁLIDO (pouco) ao âmbar profundo (muito) — o olho lê o degrau baixo
// como "pouco", não como "vazio".
//
// Fixa (não lê `--seq-*`) de propósito, espelhando a rampa divergente do modo
// Comparar (`divergente.ts`): mexer nos tokens `--seq-*` afetaria o funil do
// dashboard e as bolhas. Mantida local ao favo — o Calor segue na `lerRampaSeq`.
//
// Sem dep nova: 5 stops literais bastam para o `colorRange` do HexagonLayer e
// para o gradiente CSS da legenda (LegendaEscala).

/** 5 stops do dourado pálido (baixo) ao âmbar profundo (alto). Tuplas RGB
 *  (0..255) no formato que o `colorRange` do deck.gl espera. */
export const RAMPA_FAVO_RGB: ReadonlyArray<[number, number, number]> = [
  [239, 221, 168], // baixo — dourado pálido ("pouco")
  [223, 196, 122],
  [196, 169, 97], // dourado do tema (--seq token)
  [150, 118, 58],
  [94, 71, 28], // alto — âmbar profundo ("muito")
] as const

/** Mesmas cores em CSS hex — usadas pela legenda (gradient da LegendaEscala). */
export const RAMPA_FAVO_CSS: readonly string[] = [
  "#EFDDA8",
  "#DFC47A",
  "#C4A961",
  "#96763A",
  "#5E471C",
] as const
