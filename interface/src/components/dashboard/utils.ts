const PCT_FMT_INT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const PCT_FMT_DEC = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })

export function formatPercent(valor: number | null): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—"
  if (Number.isInteger(valor)) return `${PCT_FMT_INT.format(valor)}%`
  return `${PCT_FMT_DEC.format(valor)}%`
}

const DELTA_FMT = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })

export function formatDeltaPercentual(valor: number, sufixo: "%" | "pp"): string {
  if (Math.abs(valor) < 0.05) return `0${sufixo}`
  const sinal = valor > 0 ? "+" : "−"
  return `${sinal}${DELTA_FMT.format(Math.abs(valor))}${sufixo}`
}

const MES_CURTO_FMT = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  timeZone: "America/Sao_Paulo",
})

const ANO_FMT = new Intl.DateTimeFormat("pt-BR", {
  year: "numeric",
  timeZone: "America/Sao_Paulo",
})

function dataDeIsoYmd(iso: string): Date {
  return new Date(`${iso}T12:00:00-03:00`)
}

function formatarTrechoCurto(iso: string): string {
  return MES_CURTO_FMT.format(dataDeIsoYmd(iso))
    .replace(".", "")
    .replace(" de ", " ")
}

export function formatRangeAbsoluto(de: string, ate: string): string {
  const inicio = formatarTrechoCurto(de)
  const fim = formatarTrechoCurto(ate)
  const ano = ANO_FMT.format(dataDeIsoYmd(ate))
  return `${inicio} – ${fim} ${ano}`
}

export function hojeBrtIso(): string {
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
  return fmt.format(new Date())
}

export function diffDiasInclusivo(deIso: string, ateIso: string): number {
  const de = dataDeIsoYmd(deIso)
  const ate = dataDeIsoYmd(ateIso)
  const ms = ate.getTime() - de.getTime()
  return Math.round(ms / (1000 * 60 * 60 * 24)) + 1
}

export function calcularDeltaPercentual(atual: number, anterior: number): number {
  if (anterior === 0) return 0
  return ((atual - anterior) / anterior) * 100
}
