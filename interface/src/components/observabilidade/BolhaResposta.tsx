"use client"

import { useState } from "react"
import { toast } from "sonner"
import { MessageSquare, Star, ThumbsDown, ThumbsUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { AvaliarRequest, TurnoObservabilidade, VereditoAvaliacao } from "@/tipos/observabilidade"

/** Um turno da IA ("ela") no chat ao vivo: a bolha + avaliacao inline
 *  (bom/ruim + nota + comentario). O veredito grava na hora; nota e comentario
 *  so persistem junto de um veredito ja escolhido (o backend exige veredito). */
export function BolhaResposta({
  turno,
  onAvaliar,
}: {
  turno: TurnoObservabilidade
  onAvaliar: (respostaIaId: string, body: AvaliarRequest) => Promise<unknown>
}) {
  const av = turno.avaliacao
  const [veredito, setVeredito] = useState<VereditoAvaliacao | null>(av?.veredito ?? null)
  const [nota, setNota] = useState<number | null>(av?.nota ?? null)
  const [comentario, setComentario] = useState(av?.comentario ?? "")
  const [comentando, setComentando] = useState(Boolean(av?.comentario))
  const [salvando, setSalvando] = useState(false)

  const salvar = async (v: VereditoAvaliacao, n: number | null, c: string) => {
    setSalvando(true)
    try {
      await onAvaliar(turno.resposta_ia_id, { veredito: v, nota: n, comentario: c.trim() || null })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar avaliação")
    } finally {
      setSalvando(false)
    }
  }

  const escolherVeredito = (v: VereditoAvaliacao) => {
    setVeredito(v)
    void salvar(v, nota, comentario)
  }
  const escolherNota = (n: number) => {
    const nova = nota === n ? null : n
    setNota(nova)
    if (veredito) void salvar(veredito, nova, comentario)
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <span className="pr-1 font-mono text-[10px] uppercase tracking-wide text-text-muted">ela (IA)</span>

      <div
        className={cn(
          "max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-br-sm border px-3 py-2 text-sm text-text-primary transition-colors",
          veredito === "bom" && "border-state-active/40 bg-state-active/10",
          veredito === "ruim" && "border-state-lost/40 bg-state-lost/10",
          veredito === null && "border-border bg-surface",
        )}
      >
        {turno.resposta_ia.conteudo}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={salvando}
          onClick={() => escolherVeredito("bom")}
          className={cn(
            "h-7 px-2.5 text-xs",
            veredito === "bom" && "border-state-active bg-state-active/15 text-state-active",
          )}
        >
          <ThumbsUp className="size-3.5" /> bom
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={salvando}
          onClick={() => escolherVeredito("ruim")}
          className={cn(
            "h-7 px-2.5 text-xs",
            veredito === "ruim" && "border-state-lost bg-state-lost/15 text-state-lost",
          )}
        >
          <ThumbsDown className="size-3.5" /> ruim
        </Button>

        <div className="flex items-center pl-0.5" role="group" aria-label="Nota">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => escolherNota(n)}
              aria-label={`Nota ${n}`}
              className="p-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
            >
              <Star
                size={14}
                strokeWidth={1.5}
                className={cn(
                  nota != null && n <= nota ? "fill-gold-500 text-gold-500" : "text-border",
                )}
              />
            </button>
          ))}
        </div>

        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setComentando((v) => !v)}
          className={cn("h-7 px-2 text-xs text-text-muted", comentario && "text-text-brand")}
          aria-label="Adicionar comentário"
        >
          <MessageSquare className="size-3.5" />
        </Button>
      </div>

      {comentando && (
        <Textarea
          rows={1}
          value={comentario}
          onChange={(e) => setComentario(e.target.value)}
          onBlur={() => {
            // so persiste a obs junto de um veredito ja existente (o rotulo exige veredito).
            if (veredito && comentario !== (av?.comentario ?? "")) void salvar(veredito, nota, comentario)
          }}
          maxLength={2000}
          placeholder="o que o vendedor faria diferente?"
          className="w-72 max-w-full text-xs"
        />
      )}
    </div>
  )
}
