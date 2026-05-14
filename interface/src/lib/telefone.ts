// Helpers para inputs controlados de telefone BR.
// Mantemos só dígitos no estado e usamos `formatarTelefoneBR` apenas no `value` do <input>.
// Para exibição em listas/cards usamos `formatTelefone` em `formatters.ts`.

export function extrairDigitosTelefone(input: string): string {
  return input.replace(/\D/g, "").slice(0, 11)
}

export function formatarTelefoneBR(digitos: string): string {
  const d = digitos
  if (d.length === 0) return ""
  if (d.length <= 2) return `(${d}`
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`
}

export function paraE164BR(digitos: string): string {
  return `+55${digitos}`
}

export function deE164BR(e164: string | null | undefined): string {
  if (!e164) return ""
  const match = e164.match(/^\+55(\d{10,11})$/)
  return match ? match[1] : ""
}
