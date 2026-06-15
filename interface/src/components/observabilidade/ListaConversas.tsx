"use client"

import type { AvaliarRequest, TurnoObservabilidade } from "@/tipos/observabilidade"

import { ConversaChat } from "./ConversaChat"
import { agruparConversas } from "./timeline"

/** Turnos do trafego agrupados por conversa (um chat cada). */
export function ListaConversas({
  turnos,
  onAvaliar,
}: {
  turnos: TurnoObservabilidade[]
  onAvaliar: (respostaIaId: string, body: AvaliarRequest) => Promise<unknown>
}) {
  const conversas = agruparConversas(turnos)

  return (
    <div className="flex flex-col gap-5">
      {conversas.map((c) => (
        <ConversaChat key={c.conversaId} conversa={c} onAvaliar={onAvaliar} />
      ))}
    </div>
  )
}
