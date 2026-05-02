export function formatTelefone(input: string): string {
  let digitos = input.split('@')[0].replace(/\D/g, '')
  if (digitos.startsWith('55') && digitos.length >= 12) {
    digitos = digitos.slice(2)
  }
  if (digitos.length === 11) {
    return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 7)}-${digitos.slice(7)}`
  }
  if (digitos.length === 10) {
    return `(${digitos.slice(0, 2)}) ${digitos.slice(2, 6)}-${digitos.slice(6)}`
  }
  return input.split('@')[0].replace(/^\+?55/, '')
}

export const formatBRL = (n: number) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(n)

export const formatDataHora = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso))

export const formatData = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso))

export const formatHorario = (iso: string) =>
  new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
  }).format(new Date(iso))

export function formatTempoRelativo(iso: string, agora = new Date()): string {
  const diffMs = agora.getTime() - new Date(iso).getTime()
  const min = Math.floor(diffMs / 60_000)
  if (min < 1) return 'agora'
  if (min < 60) return `há ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `há ${h} h`
  const d = Math.floor(h / 24)
  return `há ${d} d`
}

export function formatDiaSemana(date: Date): string {
  return new Intl.DateTimeFormat('pt-BR', {
    weekday: 'long', timeZone: 'America/Sao_Paulo',
  }).format(date)
}

export function formatRotulo(valor: string | null | undefined): string | null {
  if (!valor) return null
  const limpo = valor.replaceAll('_', ' ').trim()
  if (!limpo) return null
  return limpo.charAt(0).toUpperCase() + limpo.slice(1)
}
