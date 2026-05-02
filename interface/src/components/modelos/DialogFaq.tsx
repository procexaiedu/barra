"use client"

import { useState } from "react"
import { Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import type { FaqInput, FaqItem } from "@/tipos/modelos"

export function DialogFaq({
  open,
  faq,
  onOpenChange,
  onSalvar,
}: {
  open: boolean
  faq: FaqItem | null
  onOpenChange: (open: boolean) => void
  onSalvar: (input: FaqInput, faqId?: string) => Promise<void>
}) {
  const [pergunta, setPergunta] = useState(faq?.pergunta ?? "")
  const [resposta, setResposta] = useState(faq?.resposta ?? "")
  const [tags, setTags] = useState((faq?.tags ?? []).join(", "))
  const [submitting, setSubmitting] = useState(false)
  const valido = pergunta.trim().length > 0 && pergunta.length <= 300 && resposta.trim().length > 0 && resposta.length <= 2000

  const submit = async () => {
    if (!valido) return
    setSubmitting(true)
    try {
      await onSalvar({
        pergunta: pergunta.trim(),
        resposta: resposta.trim(),
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      }, faq?.id)
      toast.success(faq ? "Resposta atualizada" : "Resposta adicionada")
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar resposta")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !submitting && onOpenChange(value)}>
      <DialogContent className="w-full max-w-2xl rounded-lg border border-border bg-popover p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <DialogTitle className="text-lg font-semibold">{faq ? "Editar resposta" : "Adicionar resposta"}</DialogTitle>
            <DialogDescription>Orientação usada nos atendimentos desta modelo.</DialogDescription>
          </div>
          <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
        </div>
        <div className="space-y-4">
          <CampoArea label="Pergunta" value={pergunta} maxLength={300} onChange={setPergunta} />
          <CampoArea label="Resposta" value={resposta} maxLength={2000} onChange={setResposta} rows={8} />
          <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            Tags
            <input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </label>
        </div>
        {!valido && <p className="mt-4 text-sm text-state-lost">Pergunta e resposta são obrigatórias e precisam respeitar o limite.</p>}
        <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>Cancelar</Button>
          <Button variant="primary" onClick={submit} disabled={!valido || submitting}>
            {submitting && <Loader2 className="animate-spin" />}
            Salvar resposta
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function CampoArea({
  label,
  value,
  maxLength,
  rows = 4,
  onChange,
}: {
  label: string
  value: string
  maxLength: number
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
      {label}
      <textarea
        value={value}
        maxLength={maxLength + 100}
        rows={rows}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-input bg-input px-3 py-2 text-sm normal-case tracking-normal text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      />
      <span className={value.length > maxLength ? "text-state-lost" : "text-text-muted"}>{value.length}/{maxLength}</span>
    </label>
  )
}
