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
import { formatBRL } from "@/lib/formatters"

export function parseValorFinal(input: string) {
  const normalizado = input
    .replace(/\s/g, "")
    .replace(/\./g, "")
    .replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) ? valor : null
}

export function ModalFecharAtendimento({
  open,
  numeroCurto,
  valorAcordado,
  onFechar,
  onCancelar,
}: {
  open: boolean
  numeroCurto: number | null
  valorAcordado: number | string | null
  onFechar: (valorFinal: number) => Promise<void>
  onCancelar: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [valorFinal, setValorFinal] = useState("")
  const [erro, setErro] = useState<string | null>(null)

  const fechar = () => {
    if (submitting) return
    setValorFinal("")
    setErro(null)
    onCancelar()
  }

  const handleFechar = async () => {
    const valor = parseValorFinal(valorFinal)
    if (valor === null || valor < 0) {
      setErro("Informe um valor final válido.")
      return
    }
    setSubmitting(true)
    try {
      await onFechar(valor)
      setValorFinal("")
      setErro(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao fechar")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !submitting && !o && fechar()}>
      <AlertDialogContent className="w-[min(94vw,40rem)] max-w-none bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-base font-semibold text-text-primary">
            Fechar #{numeroCurto}?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm text-text-secondary">
            Informe o valor final bruto pago pelo cliente. Isto encerra o atendimento e conclui o bloqueio vinculado.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md bg-muted px-3 py-2.5">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
              Valor acordado
            </p>
            <p className="mt-1 font-mono text-2xl font-semibold leading-none tabular-nums text-gold-500">
              {valorAcordado != null ? formatBRL(Number(valorAcordado)) : "—"}
            </p>
          </div>
          <div>
            <label
              className="mb-1 block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
              htmlFor="valor-final-modal"
            >
              Valor final
            </label>
            <Input
              id="valor-final-modal"
              inputMode="decimal"
              value={valorFinal}
              onChange={(event) => {
                setValorFinal(event.target.value)
                setErro(null)
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  void handleFechar()
                }
              }}
              placeholder="1200,00"
              className="h-11 text-base"
              autoFocus
            />
          </div>
        </div>
        {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={fechar}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction variant="primary" onClick={handleFechar} disabled={submitting}>
            {submitting ? "Fechando..." : "Confirmar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
