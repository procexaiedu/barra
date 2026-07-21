import type { FiltrosDashboard } from "@/hooks/useDashboard"
import type { TipoEscalada } from "@/tipos/dashboard"

export const ESCALADA_FAIXAS = { bom: 25, atencao: 40 } as const
export const N_MINIMO_PARA_DELTA_PCT = 10

const DELTA_ABS_INT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })

export function formatDeltaAbsoluto(atual: number, anterior: number | null | undefined): string {
  if (anterior === null || anterior === undefined) return "—"
  const delta = atual - anterior
  if (delta === 0) return "0"
  const sinal = delta > 0 ? "+" : "−"
  return `${sinal}${DELTA_ABS_INT.format(Math.abs(delta))}`
}

export function deveSuprimirDeltaPct(base: number | null | undefined): boolean {
  if (base === null || base === undefined) return true
  return base < N_MINIMO_PARA_DELTA_PCT
}

const ROTULOS_TIPO_ESCALADA: Record<TipoEscalada, string> = {
  pix_validado: "Pix de deslocamento validado",
  pix_duvidoso: "Pix duvidoso aguardando decisão",
  foto_portaria: "Cliente chegou (foto de portaria)",
  aviso_saida: "Cliente avisou que saiu de casa",
  fora_de_oferta: "Cliente pediu valor fora da tabela",
  comportamento_atipico: "Comportamento atípico antes de confirmar",
  indisponibilidade: "Sem agenda disponível",
  video_chamada: "Hora da vídeo chamada",
  pausa_manual_operador: "Pausa manual do operador",
  outro: "Outro",
}

export function rotuloTipoEscalada(tipo: TipoEscalada): string {
  return ROTULOS_TIPO_ESCALADA[tipo] ?? tipo
}

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

export function dataDeIsoYmd(iso: string): Date {
  return new Date(`${iso}T12:00:00-03:00`)
}

const YMD_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/Sao_Paulo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

export function isoYmdDeData(data: Date): string {
  return YMD_FMT.format(data)
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

export function janelaDoPeriodo(filtros: FiltrosDashboard): { de: string; ate: string } | null {
  if (filtros.periodo === "tudo") return null
  const hoje = hojeBrtIso()
  if (filtros.periodo === "hoje") return { de: hoje, ate: hoje }
  if (filtros.periodo === "7d") {
    const base = dataDeIsoYmd(hoje)
    base.setUTCDate(base.getUTCDate() - 6)
    return { de: isoYmdDeData(base), ate: hoje }
  }
  if (filtros.periodo === "30d") {
    const base = dataDeIsoYmd(hoje)
    base.setUTCDate(base.getUTCDate() - 29)
    return { de: isoYmdDeData(base), ate: hoje }
  }
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    return { de: filtros.de, ate: filtros.ate }
  }
  return null
}
