"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { ModalFecharAtendimento } from "@/components/atendimentos/ModalFecharAtendimento"
import { ModalPerderAtendimento } from "@/components/atendimentos/ModalPerderAtendimento"
import type { AtendimentoOperacional, MotivoPerda } from "@/tipos/atendimentos"

type Dialog = "devolver" | "fechar" | "perder" | null

function motivoPausaLabel(motivo: AtendimentoOperacional["ia_pausada_motivo"]): string {
  if (motivo === "pix_em_revisao") return "Pix em revisão"
  if (motivo === "handoff_ia") return "Aguardando você"
  if (motivo === "modelo_em_atendimento") return "Modelo atendendo"
  return "—"
}

export function AcoesAtendimento({
  atendimento,
  onDevolver,
  onFechar,
  onPerder,
}: {
  atendimento: AtendimentoOperacional
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
}) {
  const [dialog, setDialog] = useState<Dialog>(null)
  const [submitting, setSubmitting] = useState(false)
  const readOnly = atendimento.estado === "Fechado" || atendimento.estado === "Perdido"

  if (readOnly) return null

  const handleDevolver = async () => {
    setSubmitting(true)
    try {
      await onDevolver(atendimento.id)
      toast.success(`Atendimento #${atendimento.numero_curto} devolvido para a IA`)
      setDialog(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao devolver")
    } finally {
      setSubmitting(false)
    }
  }

  const devolverVisivel = atendimento.ia_pausada

  return (
    <div className="flex flex-wrap gap-2">
      {devolverVisivel && (
        <Button variant="primary" onClick={() => setDialog("devolver")}>
          Devolver para IA
        </Button>
      )}
      <Button
        variant={devolverVisivel ? "secondary" : "primary"}
        onClick={() => setDialog("fechar")}
      >
        Converter
      </Button>
      <Button variant="danger" onClick={() => setDialog("perder")}>
        Perder
      </Button>

      <AlertDialog open={dialog === "devolver"} onOpenChange={(open) => !submitting && setDialog(open ? "devolver" : null)}>
        <AlertDialogContent className="w-[min(94vw,28rem)] max-w-none bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Devolver #{atendimento.numero_curto} para a IA?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A IA volta a responder o cliente na próxima mensagem.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {atendimento.ia_pausada && (
            <div className="flex items-center gap-3 rounded-md border border-border-subtle bg-surface px-3 py-2 text-xs">
              <span className="text-text-muted">IA pausada</span>
              <span className="text-text-primary">{motivoPausaLabel(atendimento.ia_pausada_motivo)}</span>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="primary" onClick={handleDevolver} disabled={submitting}>
              {submitting ? "Devolvendo..." : "Confirmar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ModalFecharAtendimento
        open={dialog === "fechar"}
        numeroCurto={atendimento.numero_curto}
        valorAcordado={atendimento.valor_acordado}
        onFechar={async (valorFinal) => {
          await onFechar(atendimento.id, valorFinal)
          setDialog(null)
        }}
        onCancelar={() => setDialog(null)}
      />

      <ModalPerderAtendimento
        open={dialog === "perder"}
        numeroCurto={atendimento.numero_curto}
        valorAcordado={atendimento.valor_acordado}
        onPerder={async (motivo, observacao) => {
          await onPerder(atendimento.id, motivo, observacao)
          setDialog(null)
        }}
        onCancelar={() => setDialog(null)}
      />
    </div>
  )
}
