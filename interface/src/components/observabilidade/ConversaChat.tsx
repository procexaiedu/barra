"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { AvaliarRequest } from "@/tipos/observabilidade"

import { BolhaResposta } from "./BolhaResposta"
import type { ConversaAvaliacao } from "./timeline"

/** Uma conversa do trafego renderizada como chat estilo WhatsApp: cliente a
 *  esquerda, ela (IA) a direita (avaliavel inline), troca de atendimento como
 *  divisoria central. */
export function ConversaChat({
  conversa,
  onAvaliar,
}: {
  conversa: ConversaAvaliacao
  onAvaliar: (respostaIaId: string, body: AvaliarRequest) => Promise<unknown>
}) {
  const { modeloNome, clienteLabel, itens, total, avaliadas } = conversa
  const completa = total > 0 && avaliadas === total

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-4 py-2.5">
        <p className="text-[13px] text-text-secondary">
          <span className="font-medium text-text-primary">{modeloNome}</span>
          <span className="text-text-muted"> · {clienteLabel}</span>
        </p>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px]",
            completa ? "bg-emerald-500/15 text-emerald-600" : "bg-muted text-text-muted",
          )}
        >
          {avaliadas}/{total} avaliadas
        </span>
      </div>

      <div className="flex flex-col gap-2.5 p-4">
        {itens.map((m, i) => {
          if (m.tipo === "cliente") {
            return (
              <div key={i} className="flex justify-start">
                <div className="max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-sm text-text-primary">
                  {m.texto}
                </div>
              </div>
            )
          }
          if (m.tipo === "atendimento") {
            return (
              <div key={i} className="flex justify-center py-0.5">
                <span className="rounded-full bg-muted/60 px-3 py-1 text-[11px] text-text-muted">
                  Atendimento #{m.numeroCurto}
                </span>
              </div>
            )
          }
          return <BolhaResposta key={i} turno={m.turno} onAvaliar={onAvaliar} />
        })}
      </div>
    </Card>
  )
}
