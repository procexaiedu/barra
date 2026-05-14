import type { BloqueioAgenda } from "@/tipos/agenda"

/**
 * Retorna "HH:MM" em BRT a partir de um ISO. Usado em previews de drag para
 * mostrar o horário-alvo enquanto o usuário arrasta um bloqueio.
 */
export function horarioDeIso(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso))
  const h = parts.find((p) => p.type === "hour")?.value ?? "00"
  const m = parts.find((p) => p.type === "minute")?.value ?? "00"
  return `${h}:${m}`
}

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

function diffDias(de: string, para: string): number {
  // Strings YYYY-MM-DD em BRT — diff em dias inteiros.
  const a = new Date(`${de}T12:00:00-03:00`).getTime()
  const b = new Date(`${para}T12:00:00-03:00`).getTime()
  return Math.round((b - a) / (24 * 60 * 60 * 1000))
}

/**
 * Calcula novo (inicio, fim) ISO a partir de delta Y em pixels + droppable alvo.
 * Consolida a lógica antes duplicada entre onDragMove/handleDragEnd da GradeSemanal:
 *  - aplica deltaTempoIso em ambos os limites (snap de horário);
 *  - se mudou de coluna (overId difere de dataOriginal), soma a diferença em dias.
 * Pura — testável isoladamente.
 */
export function calcularDestino(
  bloqueio: { inicio: string; fim: string },
  deltaY: number,
  overId: string | null,
  dataOriginal: string,
  horaHeight = 80,
  snapMin = 15,
): { inicioIso: string; fimIso: string } {
  const inicioComDelta = deltaTempoIso(bloqueio.inicio, deltaY, horaHeight, snapMin)
  const fimComDelta = deltaTempoIso(bloqueio.fim, deltaY, horaHeight, snapMin)
  if (!overId || overId === dataOriginal) {
    return { inicioIso: inicioComDelta, fimIso: fimComDelta }
  }
  const diasDelta = diffDias(dataOriginal, overId)
  const msDia = 24 * 60 * 60 * 1000
  return {
    inicioIso: new Date(new Date(inicioComDelta).getTime() + diasDelta * msDia).toISOString(),
    fimIso: new Date(new Date(fimComDelta).getTime() + diasDelta * msDia).toISOString(),
  }
}
