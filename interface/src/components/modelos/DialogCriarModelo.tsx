"use client"

import { useState } from "react"
import { Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import type { CriarModeloInput, TipoAtendimento } from "@/tipos/modelos"

const inicial: CriarModeloInput = {
  nome: "",
  idade: 0,
  numero_whatsapp: "",
  valor_padrao: 0,
  idiomas: ["pt-BR"],
  tipo_atendimento_aceito: ["interno"],
}

export function DialogCriarModelo({
  open,
  onOpenChange,
  onCriar,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCriar: (input: CriarModeloInput) => Promise<void>
}) {
  const [form, setForm] = useState<CriarModeloInput>(inicial)
  const [idiomasInput, setIdiomasInput] = useState("pt-BR")
  const [submitting, setSubmitting] = useState(false)
  const [tentou, setTentou] = useState(false)
  const valido =
    form.nome.trim().length > 0 &&
    form.nome.length <= 100 &&
    form.idade > 0 &&
    /^\+55\d{10,11}$/.test(form.numero_whatsapp) &&
    form.tipo_atendimento_aceito.length > 0 &&
    idiomasInput.split(",").map((i) => i.trim()).filter(Boolean).length > 0

  const submit = async () => {
    setTentou(true)
    if (!valido) return
    setSubmitting(true)
    try {
      await onCriar({
        ...form,
        nome: form.nome.trim(),
        valor_padrao: 0,
        idiomas: idiomasInput.split(",").map((i) => i.trim()).filter(Boolean),
      })
      toast.success(`Modelo ${form.nome.trim()} criada`)
      setForm(inicial)
      setIdiomasInput("pt-BR")
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao criar modelo")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !submitting && onOpenChange(value)}>
      <DialogContent className="w-full max-w-xl rounded-lg border border-border bg-popover p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <DialogTitle className="text-lg font-semibold">Adicionar modelo</DialogTitle>
            <DialogDescription>Cadastre o mínimo para operar; os programas e valores ficam no Perfil.</DialogDescription>
          </div>
          <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <Campo label="Nome" className="col-span-2">
            <Input value={form.nome} maxLength={100} onChange={(e) => setForm({ ...form, nome: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Idade">
            <Input type="number" value={form.idade || ""} onChange={(e) => setForm({ ...form, idade: Number(e.target.value) })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Número de WhatsApp" className="col-span-2">
            <Input value={form.numero_whatsapp} placeholder="+5521987654321" onChange={(e) => setForm({ ...form, numero_whatsapp: e.target.value })} className="h-10 bg-input" />
          </Campo>
          <Campo label="Idiomas">
            <Input value={idiomasInput} placeholder="pt-BR, en-US" onChange={(e) => setIdiomasInput(e.target.value)} className="h-10 bg-input" />
          </Campo>
          <div className="col-span-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">Atende em</p>
            <TipoChecks
              value={form.tipo_atendimento_aceito}
              onChange={(tipo_atendimento_aceito) => setForm({ ...form, tipo_atendimento_aceito })}
            />
          </div>
        </div>
        {tentou && !valido && (
          <p className="mt-4 text-sm text-state-lost">Preencha nome, idade, número no formato +55, idioma e pelo menos uma opção de atendimento.</p>
        )}
        <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={submitting}>Cancelar</Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="animate-spin" />}
            Criar modelo
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Campo({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted ${className ?? ""}`}>
      {label}
      {children}
    </label>
  )
}

export function TipoChecks({
  value,
  onChange,
}: {
  value: TipoAtendimento[]
  onChange: (value: TipoAtendimento[]) => void
}) {
  const toggle = (tipo: TipoAtendimento) => {
    if (value.includes(tipo)) onChange(value.filter((v) => v !== tipo))
    else onChange([...value, tipo])
  }
  return (
    <div className="flex gap-4">
      {(["interno", "externo"] as TipoAtendimento[]).map((tipo) => (
        <label key={tipo} className="inline-flex items-center gap-2 text-sm normal-case tracking-normal text-text-secondary">
          <input
            type="checkbox"
            checked={value.includes(tipo)}
            onChange={() => toggle(tipo)}
            className="size-4 rounded border-border bg-input accent-primary"
          />
          {tipo === "interno" ? "No local dela" : "No local do cliente"}
        </label>
      ))}
    </div>
  )
}
