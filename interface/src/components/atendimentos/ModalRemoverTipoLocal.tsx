"use client"

import { useState } from "react"
import { toast } from "sonner"
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
import { api } from "@/lib/api"
import { formatRotulo } from "@/lib/formatters"

const SEM_TIPO = "__sem_tipo__"

const controlClassName =
  "h-10 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"

function rotulo(v: string): string {
  return formatRotulo(v) ?? v
}

/**
 * Modal de substituição/limpeza ao remover um tipo de local que está em uso por
 * N atendimentos. Para tipo sem uso, o consumidor confirma direto (sem este modal).
 */
export function ModalRemoverTipoLocal({
  nome,
  contagem,
  tiposExistentes,
  onRemovido,
  onCancelar,
}: {
  /** tipo a remover; null = modal fechado */
  nome: string | null
  contagem: number
  /** todos os tipos existentes (inclui o que será removido) */
  tiposExistentes: string[]
  onRemovido: () => void
  onCancelar: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [substituto, setSubstituto] = useState("")

  const aberto = nome !== null

  const opcoes = tiposExistentes.filter((t) => t !== nome)

  const fechar = () => {
    if (submitting) return
    setSubstituto("")
    onCancelar()
  }

  const handleConfirmar = async () => {
    if (!nome) return
    setSubmitting(true)
    try {
      const query =
        substituto && substituto !== SEM_TIPO
          ? `?substituto=${encodeURIComponent(substituto)}`
          : ""
      await api(`/v1/atendimentos/tipos-local/${encodeURIComponent(nome)}${query}`, {
        method: "DELETE",
      })
      toast.success(`Tipo de local "${rotulo(nome)}" removido`)
      setSubstituto("")
      onRemovido()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover tipo")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AlertDialog open={aberto} onOpenChange={(o) => !submitting && !o && fechar()}>
      <AlertDialogContent className="w-[min(94vw,32rem)] max-w-none bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-base font-semibold text-text-primary">
            Remover &ldquo;{nome ? rotulo(nome) : ""}&rdquo;?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm text-text-secondary">
            &ldquo;{nome ? rotulo(nome) : ""}&rdquo; está em {contagem}{" "}
            {contagem === 1 ? "atendimento" : "atendimentos"}. Escolha um tipo
            substituto ou deixe esses atendimentos sem tipo.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="flex flex-col gap-1.5">
          <label
            className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
            htmlFor="substituto-tipo-local"
          >
            Substituir por
          </label>
          <select
            id="substituto-tipo-local"
            value={substituto}
            onChange={(e) => setSubstituto(e.target.value)}
            className={controlClassName}
            disabled={submitting}
          >
            <option value="">Selecione…</option>
            {opcoes.map((t) => (
              <option key={t} value={t}>
                {rotulo(t)}
              </option>
            ))}
            <option value={SEM_TIPO}>Deixar sem tipo</option>
          </select>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={fechar}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction
            variant="primary"
            onClick={handleConfirmar}
            disabled={submitting || substituto === ""}
          >
            {submitting ? "Removendo…" : "Confirmar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
