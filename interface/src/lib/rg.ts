// Utilitários de RG (ADR 0007). Backend armazena normalizado; aqui é UX.
// RG não tem formato único nacional: o nº de dígitos varia por estado e o dígito
// verificador pode ser uma letra (X). Por isso não travamos em 9 dígitos.

/**
 * Mantém só dígitos e um X final opcional (dígito verificador), em maiúsculo.
 * Tudo após o X é descartado; comprimento livre (varia por estado).
 */
export function normalizarRg(valor: string): string {
  const limpo = valor.toUpperCase().replace(/[^0-9X]/g, "")
  // X só vale como dígito verificador no fim — ignora X no meio e o que vier depois.
  const match = limpo.match(/^[0-9]*X?/)
  return match ? match[0] : ""
}

/**
 * Aplica a máscara 99.999.999-9 progressivamente sobre os dígitos normalizados.
 * O último caractere (dígito ou X) vira o dígito verificador após o hífen; o
 * restante é agrupado em trincas separadas por ponto. Comprimentos maiores que
 * o padrão de 9 ficam agrupados sem quebrar (não trava por estado).
 */
export function formatarRg(valor: string): string {
  const d = normalizarRg(valor)
  if (d.length <= 1) return d
  const corpo = d.slice(0, -1)
  const dv = d.slice(-1)
  const grupos = corpo.match(/.{1,3}(?=(.{3})*$)|.{1,3}$/g) ?? [corpo]
  return `${grupos.join(".")}-${dv}`
}
