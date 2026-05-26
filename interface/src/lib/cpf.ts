// Utilitários de CPF (ADR 0007). Backend normaliza/valida de novo; aqui é UX.

/** Mantém só dígitos, no máximo 11. */
export function normalizarCpf(valor: string): string {
  return valor.replace(/\D/g, "").slice(0, 11)
}

/** Aplica a máscara 000.000.000-00 progressivamente. */
export function formatarCpf(valor: string): string {
  const d = normalizarCpf(valor)
  if (d.length <= 3) return d
  if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`
  if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`
}

/** Valida os 11 dígitos + dígitos verificadores; rejeita sequências repetidas. */
export function cpfValido(valor: string): boolean {
  const d = normalizarCpf(valor)
  if (d.length !== 11) return false
  if (d === d[0].repeat(11)) return false
  const dv = (base: string): number => {
    const peso = base.length + 1
    const soma = base.split("").reduce((acc, ch, i) => acc + Number(ch) * (peso - i), 0)
    const resto = soma % 11
    return resto < 2 ? 0 : 11 - resto
  }
  return dv(d.slice(0, 9)) === Number(d[9]) && dv(d.slice(0, 10)) === Number(d[10])
}
