"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { FalaParaRotular } from "@/tipos/calibracao"

import { BolhaIA } from "./BolhaIA"
import { montarChat } from "./timeline"

/** Uma conversa renderizada como chat estilo WhatsApp: cliente a esquerda, ela (IA)
 *  a direita (avaliavel inline), atos como divisoria central. */
export function ConversaChat({
  cenario,
  falas,
  onMarcar,
}: {
  cenario: string
  falas: FalaParaRotular[]
  onMarcar: (falaPk: string, passou: boolean, observacao: string) => void
}) {
  const msgs = montarChat(falas)
  const rotuladas = falas.filter((f) => f.meu_rotulo !== null).length
  const completa = rotuladas === falas.length

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-4 py-2.5">
        <p className="font-mono text-[13px] text-text-secondary">{cenario}</p>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px]",
            completa ? "bg-emerald-500/15 text-emerald-600" : "bg-muted text-text-muted",
          )}
        >
          {rotuladas}/{falas.length} avaliadas
        </span>
      </div>

      <div className="flex flex-col gap-2.5 p-4">
        {msgs.map((m, i) => {
          if (m.tipo === "cliente") {
            return (
              <div key={i} className="flex justify-start">
                <div className="max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-sm text-text-primary">
                  {m.texto}
                </div>
              </div>
            )
          }
          if (m.tipo === "ato") {
            return (
              <div key={i} className="flex justify-center py-0.5">
                <span className="rounded-full bg-muted/60 px-3 py-1 text-[11px] text-text-muted">
                  {m.texto}
                </span>
              </div>
            )
          }
          return (
            <BolhaIA
              key={i}
              texto={m.texto}
              citado={m.citado}
              fala={m.fala}
              onMarcar={onMarcar}
            />
          )
        })}
      </div>
    </Card>
  )
}
