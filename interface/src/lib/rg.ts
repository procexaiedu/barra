// Utilitários de RG (ADR 0007). Backend armazena normalizado; aqui é UX.
// O dígito verificador pode ser uma letra (X). Limitamos ao padrão de 9 posições
// (8 dígitos + verificador), que é o que a máscara 00.000.000-0 desenha.

/** Padrão de 9 posições: 8 dígitos + 1 verificador (dígito ou X). */
const RG_MAX = 9

/**
 * Mantém só dígitos e um X final opcional (dígito verificador), em maiúsculo,
 * limitado a {@link RG_MAX} posições. Tudo após o X ou além do limite é descartado.
 */
export function normalizarRg(valor: string): string {
  const limpo = valor.toUpperCase().replace(/[^0-9X]/g, "")
  // X só vale como dígito verificador no fim — ignora X no meio e o que vier depois.
  const match = limpo.match(/^[0-9]*X?/)
  return (match ? match[0] : "").slice(0, RG_MAX)
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
