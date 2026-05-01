"use client"

import { useState } from "react"
import type { KeyboardEvent } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

const LIMITE = 2000
const MOSTRAR_CONTADOR_ACIMA = 1500
const ALERTAR_ACIMA = 1900

export function ObservacoesInternas({
  valor,
  dirty,
  onChange,
  onSave,
  onDescartar,
}: {
  valor: string
  dirty: boolean
  onChange: (valor: string) => void
  onSave: () => Promise<void>
  onDescartar: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const tooLong = valor.length > LIMITE

  const handleChange = (proximo: string) => {
    if (erro) setErro(null)
    onChange(proximo)
  }

  const handleSave = async () => {
    if (tooLong || submitting || !dirty) return
    setSubmitting(true)
    setErro(null)
    try {
      await onSave()
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro desconhecido")
    } finally {
      setSubmitting(false)
    }
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault()
      void handleSave()
    }
  }

  const mostrarContador = valor.length > MOSTRAR_CONTADOR_ACIMA
  const contadorAlerta = valor.length > ALERTAR_ACIMA

  return (
    <section
      aria-label="Observações internas"
      className="rounded-lg border border-border bg-card p-6"
    >
      <p className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
        OBSERVAÇÕES INTERNAS
      </p>
      <Textarea
        value={valor}
        onChange={(event) => handleChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={submitting}
        placeholder="Anotações sobre esta conversa..."
        aria-invalid={tooLong || undefined}
        className="mt-3 min-h-[120px] resize-y"
      />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-text-muted">
          Visíveis apenas para Fernando e a modelo. A IA não consulta este campo.
        </p>
        {mostrarContador && (
          <span
            className={cn(
              "text-[12px] font-medium",
              contadorAlerta ? "text-state-lost" : "text-text-muted"
            )}
          >
            {valor.length} / {LIMITE}
          </span>
        )}
      </div>
      {erro && <p className="mt-2 text-[13px] text-state-lost">{erro}</p>}
      {dirty && (
        <div className="mt-4 flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onDescartar} disabled={submitting}>
            Descartar
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={submitting || tooLong}
          >
            {submitting && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
            Salvar observações
          </Button>
        </div>
      )}
    </section>
  )
}
