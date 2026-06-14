"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Star, ThumbsDown, ThumbsUp } from "lucide-react"

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { AvaliarRequest, TurnoObservabilidade, VereditoAvaliacao } from "@/tipos/observabilidade"

export function DialogAvaliar({
  turno,
  onClose,
  onAvaliar,
}: {
  turno: TurnoObservabilidade
  onClose: () => void
  onAvaliar: (respostaIaId: string, body: AvaliarRequest) => Promise<unknown>
}) {
  const [veredito, setVeredito] = useState<VereditoAvaliacao | null>(
    turno.avaliacao?.veredito ?? null,
  )
  const [nota, setNota] = useState<number | null>(turno.avaliacao?.nota ?? null)
  const [comentario, setComentario] = useState(turno.avaliacao?.comentario ?? "")
  const [salvando, setSalvando] = useState(false)

  const salvar = async () => {
    if (!veredito) {
      toast.error("Escolha bom ou ruim primeiro")
      return
    }
    setSalvando(true)
    try {
      await onAvaliar(turno.resposta_ia_id, {
        veredito,
        nota,
        comentario: comentario.trim() || null,
      })
      toast.success("Avaliação salva")
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar avaliação")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
    >
      <DialogContent size="md">
        <DialogHeader className="flex-col items-start gap-1">
          <DialogTitle>Avaliar resposta da IA</DialogTitle>
          <DialogDescription>
            {turno.modelo_nome} · {turno.cliente_nome ?? turno.cliente_telefone}
            {turno.numero_curto != null ? ` · #${turno.numero_curto}` : ""}
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
          {turno.mensagem_cliente && (
            <div>
              <p className="mb-1 text-xs font-medium text-text-muted">Cliente</p>
              <p className="whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm text-text-primary">
                {turno.mensagem_cliente.conteudo}
              </p>
            </div>
          )}
          <div>
            <p className="mb-1 text-xs font-medium text-text-muted">Resposta da IA</p>
            <p className="whitespace-pre-wrap rounded-lg bg-accent px-3 py-2 text-sm text-text-primary">
              {turno.resposta_ia.conteudo}
            </p>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setVeredito("bom")}
              aria-pressed={veredito === "bom"}
              className={cn(
                "flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                veredito === "bom"
                  ? "border-state-active bg-state-active/15 text-state-active"
                  : "border-border text-text-muted hover:text-text-primary",
              )}
            >
              <ThumbsUp size={15} strokeWidth={1.5} />O vendedor faria assim
            </button>
            <button
              type="button"
              onClick={() => setVeredito("ruim")}
              aria-pressed={veredito === "ruim"}
              className={cn(
                "flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                veredito === "ruim"
                  ? "border-state-lost bg-state-lost/15 text-state-lost"
                  : "border-border text-text-muted hover:text-text-primary",
              )}
            >
              <ThumbsDown size={15} strokeWidth={1.5} />
              Não faria
            </button>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-text-muted">Nota (opcional)</p>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setNota(nota === n ? null : n)}
                  aria-label={`Nota ${n}`}
                  className="p-1"
                >
                  <Star
                    size={22}
                    strokeWidth={1.5}
                    className={cn(
                      nota != null && n <= nota
                        ? "fill-state-info text-state-info"
                        : "text-border",
                    )}
                  />
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-text-muted">Comentário (opcional)</p>
            <Textarea
              value={comentario}
              onChange={(e) => setComentario(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="O que o vendedor faria diferente?"
            />
          </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={salvar} disabled={salvando}>
            Salvar avaliação
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
