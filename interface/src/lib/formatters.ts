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

// Telefone "exibível": E.164 BR (10/11 dígitos após remover o 55). JID de grupo
// (@g.us / número de 18 dígitos) não é telefone de cliente e não deve virar título.
export function ehTelefoneExibivel(input: string): boolean {
  if (input.includes('@')) return false
  let digitos = input.replace(/\D/g, '')
  if (digitos.startsWith('55') && digitos.length >= 12) digitos = digitos.slice(2)
  return digitos.length === 10 || digitos.length === 11
}

// Identidade do cliente para títulos/listas: nome quando houver, senão o telefone
// formatado, senão um rótulo neutro (evita exibir o JID de 18 dígitos como nome).
export function nomeCliente(nome: string | null | undefined, telefone: string): string {
  if (nome) return nome
  if (ehTelefoneExibivel(telefone)) return formatTelefone(telefone)
  return 'Contato sem telefone'
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
  // Date-only ("2026-06-10", ex. data_desejada) parseia como meia-noite UTC e o formatter
  // em America/Sao_Paulo recua para o dia anterior; ancorar ao meio-dia UTC mantém o dia.
  }).format(new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00Z` : iso))

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

export function formatDuracaoHoras(valor: number | string | null | undefined): string | null {
  if (valor === null || valor === undefined) return null
  const horas = typeof valor === 'string' ? Number(valor) : valor
  if (!Number.isFinite(horas) || horas <= 0) return null
  const totalMin = Math.round(horas * 60)
  const h = Math.floor(totalMin / 60)
  const min = totalMin % 60
  if (h === 0) return `${min} min`
  if (min === 0) return `${h}h`
  return `${h}h${String(min).padStart(2, '0')}`
}

export function formatRotulo(valor: string | null | undefined): string | null {
  if (!valor) return null
  const limpo = valor.replaceAll('_', ' ').trim()
  if (!limpo) return null
  return limpo.charAt(0).toUpperCase() + limpo.slice(1)
}
