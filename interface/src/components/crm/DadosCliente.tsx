"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatData, formatTelefone } from "@/lib/formatters"
import type { ClienteDetalhe } from "@/tipos/crm"

export function DadosCliente({
  cliente,
  valor,
  dirty,
  onChange,
  onSave,
}: {
  cliente: ClienteDetalhe
  valor: string
  dirty: boolean
  onChange: (valor: string) => void
  onSave: () => Promise<void>
}) {
  const [submitting, setSubmitting] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const tooLong = valor.trim().length > 200

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

  return (
    <section
      aria-label="Dados do cliente"
      className="rounded-lg border border-border bg-card p-6"
    >
      <h2 className="mb-4 text-base font-semibold text-text-primary">Dados do cliente</h2>
      <dl className="space-y-4">
        <Linha rotulo="Telefone">
          <span className="font-mono text-xs text-text-muted">
            {formatTelefone(cliente.telefone)}
          </span>
        </Linha>

        <div>
          <dt className="text-xs font-medium text-text-muted">Nome</dt>
          <dd className="mt-1 flex flex-wrap items-center gap-2">
            <Input
              value={valor}
              onChange={(event) => handleChange(event.target.value)}
              disabled={submitting}
              maxLength={220}
              placeholder="Nome do cliente"
              aria-invalid={tooLong || undefined}
              className="h-9 max-w-[280px]"
            />
            <Button
              variant="secondary"
              size="sm"
              disabled={!dirty || submitting || tooLong}
              onClick={handleSave}
            >
              {submitting && <Loader2 size={14} strokeWidth={1.5} className="animate-spin" />}
              Salvar nome
            </Button>
          </dd>
          {tooLong && (
            <p className="mt-1 text-[13px] text-state-lost">Máximo 200 caracteres.</p>
          )}
          {erro && <p className="mt-1 text-[13px] text-state-lost">{erro}</p>}
        </div>

        <Linha rotulo="Primeiro contato">
          <span className="text-sm text-text-primary">
            {cliente.primeiro_contato_modelo_nome ?? "Não informado"}
          </span>
        </Linha>

        <Linha rotulo="Cliente desde">
          <span className="text-sm text-text-primary">{formatData(cliente.created_at)}</span>
        </Linha>
      </dl>
    </section>
  )
}

function Linha({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <dt className="min-w-[140px] text-xs font-medium text-text-muted">{rotulo}</dt>
      <dd>{children}</dd>
    </div>
  )
}
