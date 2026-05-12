const YMD_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Sao_Paulo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

function partesBrt(d: Date): { ano: number; mes: number; dia: number; diaSemana: number } {
  const partes = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).formatToParts(d)
  const ano = Number(partes.find((p) => p.type === "year")?.value)
  const mes = Number(partes.find((p) => p.type === "month")?.value)
  const dia = Number(partes.find((p) => p.type === "day")?.value)
  const weekdayShort = partes.find((p) => p.type === "weekday")?.value ?? "Mon"
  const mapa: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
  const diaSemana = mapa[weekdayShort] ?? 1
  return { ano, mes, dia, diaSemana }
}

function isoYmd(ano: number, mes: number, dia: number): string {
  const m = String(mes).padStart(2, "0")
  const d = String(dia).padStart(2, "0")
  return `${ano}-${m}-${d}`
}

export function hojeBrtIso(): string {
  return YMD_FMT.format(new Date())
}

export function inicioSemanaBrtIso(): string {
  const { ano, mes, dia, diaSemana } = partesBrt(new Date())
  // segunda-feira como início (ISO). Domingo (0) -> recua 6 dias.
  const offset = diaSemana === 0 ? 6 : diaSemana - 1
  const base = new Date(Date.UTC(ano, mes - 1, dia))
  base.setUTCDate(base.getUTCDate() - offset)
  return isoYmd(base.getUTCFullYear(), base.getUTCMonth() + 1, base.getUTCDate())
}

export function fimSemanaBrtIso(): string {
  const { ano, mes, dia, diaSemana } = partesBrt(new Date())
  const offset = diaSemana === 0 ? 0 : 7 - diaSemana
  const base = new Date(Date.UTC(ano, mes - 1, dia))
  base.setUTCDate(base.getUTCDate() + offset)
  return isoYmd(base.getUTCFullYear(), base.getUTCMonth() + 1, base.getUTCDate())
}

export function inicioMesBrtIso(): string {
  const { ano, mes } = partesBrt(new Date())
  return isoYmd(ano, mes, 1)
}

export function fimMesBrtIso(): string {
  const { ano, mes } = partesBrt(new Date())
  // dia 0 do mês seguinte = último dia do mês corrente
  const ultimo = new Date(Date.UTC(ano, mes, 0))
  return isoYmd(ultimo.getUTCFullYear(), ultimo.getUTCMonth() + 1, ultimo.getUTCDate())
}

const DIA_MES_FMT = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
})

export function formatarDiaMes(iso: string): string {
  // iso no formato YYYY-MM-DD; fixa meio-dia BRT para evitar drift de fuso.
  return DIA_MES_FMT.format(new Date(`${iso}T12:00:00-03:00`))
}
