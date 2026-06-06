"use client"

import type { FalaParaRotular } from "@/tipos/calibracao"

import { ConversaChat } from "./ConversaChat"
import { agruparPorConversa } from "./timeline"

/** Falas da rodada agrupadas por conversa (um chat cada) + progresso do rotulador. */
export function ListaFalas({
  falas,
  onMarcar,
}: {
  falas: FalaParaRotular[]
  onMarcar: (falaPk: string, passou: boolean, observacao: string) => void
}) {
  const rotuladas = falas.filter((f) => f.meu_rotulo !== null).length
  const conversas = agruparPorConversa(falas)

  return (
    <div className="flex flex-col gap-5">
      <p className="text-[13px] text-text-muted">
        {rotuladas}/{falas.length} falas rotuladas por você · {conversas.length} conversas
      </p>
      {conversas.map((c) => (
        <ConversaChat key={c.conversaId} cenario={c.cenario} falas={c.falas} onMarcar={onMarcar} />
      ))}
    </div>
  )
}
