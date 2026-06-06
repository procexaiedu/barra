"use client"

import { useState } from "react"
import { Check, MessageSquare, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { FalaParaRotular } from "@/tipos/calibracao"

import type { Bolha } from "./timeline"

/** Um turno da IA ("ela") no chat: 1+ bolhas do WhatsApp (cada chunk e um balao
 *  separado, com reply quando cita o cliente) + voto ✓/✕ e comentario UMA vez no
 *  turno. Veredito HOLISTICO (4 rubricas) — ver GUIA_ROTULAGEM.md. */
export function BolhaIA({
  bolhas,
  fala,
  onMarcar,
}: {
  bolhas: Bolha[]
  fala: FalaParaRotular
  onMarcar: (falaPk: string, passou: boolean, observacao: string) => void
}) {
  const voto = fala.meu_rotulo?.passou ?? null
  const [obs, setObs] = useState(fala.meu_rotulo?.observacao ?? "")
  const [comentando, setComentando] = useState(Boolean(fala.meu_rotulo?.observacao))

  return (
    <div className="flex flex-col items-end gap-1">
      <span className="pr-1 text-[10px] uppercase tracking-wide text-text-muted">ela (IA)</span>

      <div className="flex max-w-[78%] flex-col items-end gap-1">
        {bolhas.map((b, i) => (
          <div
            key={i}
            className={cn(
              "rounded-2xl rounded-br-sm border px-3 py-2 text-sm text-text-primary",
              voto === true && "border-emerald-500/40 bg-emerald-500/10",
              voto === false && "border-destructive/40 bg-destructive/10",
              voto === null && "border-primary/25 bg-primary/10",
            )}
          >
            {b.citado !== null && (
              <div className="mb-1.5 border-l-2 border-primary/70 bg-muted/60 py-1 pl-2 pr-2">
                <p className="text-[10px] font-medium text-primary">cliente</p>
                <p className="line-clamp-2 whitespace-pre-wrap text-[12px] text-text-muted">
                  {b.citado}
                </p>
              </div>
            )}
            <p className="whitespace-pre-wrap">{b.texto}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onMarcar(fala.id, true, obs)}
          className={cn(
            "h-7 px-2.5 text-xs",
            voto === true && "border-transparent bg-emerald-600 text-white hover:bg-emerald-600/90",
          )}
        >
          <Check className="size-3.5" /> passou
        </Button>
        <Button
          type="button"
          size="sm"
          variant={voto === false ? "destructive" : "outline"}
          onClick={() => onMarcar(fala.id, false, obs)}
          className="h-7 px-2.5 text-xs"
        >
          <X className="size-3.5" /> não passou
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setComentando((v) => !v)}
          className={cn("h-7 px-2 text-xs text-text-muted", obs && "text-primary")}
          aria-label="comentário"
        >
          <MessageSquare className="size-3.5" />
        </Button>
      </div>

      {comentando && (
        <Textarea
          rows={1}
          value={obs}
          onChange={(e) => setObs(e.target.value)}
          onBlur={() => {
            // so persiste a obs junto de um voto ja existente (o rotulo exige passou).
            if (voto !== null && obs !== (fala.meu_rotulo?.observacao ?? ""))
              onMarcar(fala.id, voto, obs)
          }}
          placeholder="comentário (opcional)"
          className="w-72 max-w-full text-xs"
        />
      )}
    </div>
  )
}
