"use client"

import { useState } from "react"
import { Check, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { FalaParaRotular } from "@/tipos/calibracao"

/** Uma fala da IA: contexto (historico) + a bolha a avaliar + voto ✓/✕ e comentario.
 *  Veredito HOLISTICO (4 rubricas) — ver GUIA_ROTULAGEM.md. */
export function CartaoFala({
  fala,
  onMarcar,
}: {
  fala: FalaParaRotular
  onMarcar: (passou: boolean, observacao: string) => void
}) {
  const [obs, setObs] = useState(fala.meu_rotulo?.observacao ?? "")
  const voto = fala.meu_rotulo?.passou ?? null

  return (
    <Card className={cn("p-4", voto !== null && "ring-1 ring-primary/30")}>
      {fala.historico.length > 0 && (
        <div className="mb-3 space-y-1 rounded-md bg-muted/50 p-3 text-[13px] text-text-muted">
          {fala.historico.map((linha, i) => (
            <p key={i} className="whitespace-pre-wrap">
              {linha}
            </p>
          ))}
        </div>
      )}

      <p className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">
        ela (IA) · avalie esta fala
      </p>
      <p className="whitespace-pre-wrap rounded-md bg-primary/5 p-3 text-sm text-text-primary">
        {fala.texto_resposta}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => onMarcar(true, obs)}
          className={cn(
            voto === true && "border-transparent bg-emerald-600 text-white hover:bg-emerald-600/90",
          )}
        >
          <Check /> passou
        </Button>
        <Button
          type="button"
          variant={voto === false ? "destructive" : "outline"}
          onClick={() => onMarcar(false, obs)}
        >
          <X /> não passou
        </Button>
      </div>

      <Textarea
        rows={1}
        value={obs}
        onChange={(e) => setObs(e.target.value)}
        onBlur={() => {
          // so persiste a obs junto de um voto ja existente (o rotulo exige passou).
          if (voto !== null && obs !== (fala.meu_rotulo?.observacao ?? "")) onMarcar(voto, obs)
        }}
        placeholder="comentário (opcional)"
        className="mt-2"
      />
    </Card>
  )
}
