"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Input } from "@/components/ui/input"
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
import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import type { MotivoPerda } from "@/tipos/atendimentos"

const motivos: { value: MotivoPerda; label: string }[] = [
  { value: "preco", label: "Preço" },
  { value: "sumiu", label: "Sumiu" },
  { value: "risco", label: "Risco" },
  { value: "indisponibilidade", label: "Indisponibilidade" },
  { value: "fora_de_area", label: "Fora de área" },
  { value: "outro", label: "Outro" },
]

export function ModalPerderAtendimento({
  open,
  numeroCurto,
  valorAcordado,
  onPerder,
  onCancelar,
}: {
  open: boolean
  numeroCurto: number | null
  valorAcordado: number | string | null
  onPerder: (motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onCancelar: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [motivo, setMotivo] = useState<MotivoPerda>("sumiu")
  const [observacao, setObservacao] = useState("")
  const [erro, setErro] = useState<string | null>(null)

  const fechar = () => {
    if (submitting) return
    setObservacao("")
    setMotivo("sumiu")
    setErro(null)
    onCancelar()
  }

  const handlePerder = async () => {
    const obs = observacao.trim()
    if (motivo === "outro" && !obs) {
      setErro("Descreva o motivo na observação.")
      return
    }
    setSubmitting(true)
    try {
      await onPerder(motivo, obs || null)
      setObservacao("")
      setMotivo("sumiu")
      setErro(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao marcar como perdido")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !submitting && !o && fechar()}>
      <AlertDialogContent className="w-[min(94vw,48rem)] max-w-none bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="font-serif text-xl font-medium text-text-primary">
            Marcar #{numeroCurto} como perdido?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm text-text-secondary">
            Escolha o motivo da perda. O atendimento será encerrado.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex items-center gap-3 text-xs text-text-muted">
          <span>#{numeroCurto}</span>
          {valorAcordado != null && (
            <>
              <span aria-hidden>·</span>
              <span>valor acordado {formatBRL(Number(valorAcordado))}</span>
            </>
          )}
        </div>
        <div className="flex flex-col gap-3">
          <div>
            <span className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
              Motivo da perda
            </span>
            <div className="grid grid-cols-3 gap-2">
              {motivos.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => {
                    setMotivo(item.value)
                    setErro(null)
                  }}
                  className={cn(
                    "rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                    motivo === item.value
                      ? "border-ring bg-surface-pressed text-text-primary"
                      : "border-border-subtle bg-surface-hover text-text-secondary hover:bg-surface-pressed"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label
              className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted"
              htmlFor="observacao-perda-modal"
            >
              Observação {motivo === "outro" ? "(obrigatória)" : "(opcional)"}
            </label>
            <Input
              id="observacao-perda-modal"
              value={observacao}
              onChange={(event) => {
                setObservacao(event.target.value)
                setErro(null)
              }}
              placeholder="Descreva o motivo"
            />
          </div>
          {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={fechar}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction variant="danger" onClick={handlePerder} disabled={submitting}>
            {submitting ? "Registrando..." : "Confirmar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
