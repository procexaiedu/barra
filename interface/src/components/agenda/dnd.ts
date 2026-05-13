import type { BloqueioAgenda } from "@/tipos/agenda"

/**
 * Converte uma posição vertical em pixels para hora/minuto, aplicando snap.
 * Inverso conceitual de `horaParaY` da GradeSemanal.
 */
export function yParaHorario(
  yPx: number,
  horaHeight = 80,
  snapMin = 15,
): { hora: number; minuto: number } {
  const totalMinutos = Math.round((yPx / horaHeight) * 60)
  const snapped = Math.round(totalMinutos / snapMin) * snapMin
  const clamped = Math.max(0, snapped)
  return {
    hora: Math.floor(clamped / 60),
    minuto: clamped % 60,
  }
}

/**
 * Soma um deslocamento vertical (em pixels) a um ISO de horário e re-snap.
 * Opera em milissegundos completos para preservar bloqueios overnight.
 */
export function deltaTempoIso(
  isoOriginal: string,
  deltaPxY: number,
  horaHeight = 80,
  snapMin = 15,
): string {
  const base = new Date(isoOriginal)
  const deltaMs = (deltaPxY / horaHeight) * 60 * 60 * 1000
  const alvo = new Date(base.getTime() + deltaMs)

  const snapMs = snapMin * 60 * 1000
  const snapped = new Date(Math.round(alvo.getTime() / snapMs) * snapMs)
  return snapped.toISOString()
}

/**
 * Checa otimisticamente se [novoInicio, novoFim) sobrepõe outro bloqueio
 * ativo do mesmo conjunto, ignorando o próprio bloqueio movido e cancelados.
 * Servidor permanece autoridade.
 */
export function detectarSobreposicao(
  bloqueios: BloqueioAgenda[],
  bloqueioId: string,
  novoInicio: string,
  novoFim: string,
): boolean {
  return bloqueios.some((b) => {
    if (b.id === bloqueioId) return false
    if (b.estado === "cancelado") return false
    return b.inicio < novoFim && novoInicio < b.fim
  })
}
