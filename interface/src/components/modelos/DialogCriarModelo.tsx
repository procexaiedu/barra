"use client"

import { useState } from "react"
import { Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { ConectarWhatsappConteudo, type QrModalStatus } from "@/components/modelos/ConectarWhatsappConteudo"
import { extrairDigitosTelefone, formatarTelefoneBR, paraE164BR } from "@/lib/telefone"
import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import type { PerfilFisico } from "@/tipos/clientes"
import type { ConectarWhatsappResponse, CriarModeloInput, TipoAtendimento } from "@/tipos/modelos"

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
  onConectar,
  qr,
  qrStatus,
  qrError,
  onAtualizar,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCriar: (input: CriarModeloInput) => Promise<void>
  onConectar?: () => Promise<void>
  qr?: ConectarWhatsappResponse | null
  qrStatus?: QrModalStatus
  qrError?: string | null
  onAtualizar?: () => void
}) {
  const [form, setForm] = useState<CriarModeloInput>(inicial)
  const [numeroDigitos, setNumeroDigitos] = useState("")
  const [idiomasInput, setIdiomasInput] = useState("pt-BR")
  const [submitting, setSubmitting] = useState(false)
  const [tentou, setTentou] = useState(false)
  const [etapa, setEtapa] = useState<"form" | "qr">("form")
  const [nomeCriado, setNomeCriado] = useState("")

  const valido =
    form.nome.trim().length > 0 &&
    form.nome.length <= 100 &&
    form.idade > 0 &&
    /^\d{10,11}$/.test(numeroDigitos) &&
    form.tipo_atendimento_aceito.length > 0 &&
    idiomasInput.split(",").map((i) => i.trim()).filter(Boolean).length > 0

  const resetar = () => {
    setForm(inicial)
    setNumeroDigitos("")
    setIdiomasInput("pt-BR")
    setTentou(false)
    setEtapa("form")
    setNomeCriado("")
  }

  const handleOpenChange = (value: boolean) => {
    if (submitting) return
    if (!value) resetar()
    onOpenChange(value)
  }

  const submit = async () => {
    setTentou(true)
    if (!valido) return
    setSubmitting(true)
    try {
      const nomeTrim = form.nome.trim()
      await onCriar({
        ...form,
        nome: nomeTrim,
        numero_whatsapp: paraE164BR(numeroDigitos),
        valor_padrao: 0,
        idiomas: idiomasInput.split(",").map((i) => i.trim()).filter(Boolean),
      })
      toast.success(`Modelo ${nomeTrim} criada`)
      if (onConectar) {
        setNomeCriado(nomeTrim)
        setEtapa("qr")
        await onConectar()
      } else {
        resetar()
        onOpenChange(false)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao criar modelo")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="w-full max-w-xl rounded-lg border border-border bg-popover p-6">
        {etapa === "form" ? (
          <>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <DialogTitle className="text-lg font-semibold">Adicionar modelo</DialogTitle>
                <DialogDescription>Cadastre o mínimo para operar; os programas e valores ficam no Perfil.</DialogDescription>
              </div>
              <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
            </div>
            <div className="space-y-6">
              <section className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-text-brand">Dados básicos</h3>
                <div className="grid grid-cols-3 gap-5">
                  <Campo label="Nome" className="col-span-2">
                    <Input value={form.nome} maxLength={100} onChange={(e) => setForm({ ...form, nome: e.target.value })} className="h-10 bg-input border-border-strong" />
                  </Campo>
                  <Campo label="Idade">
                    <Input type="number" value={form.idade || ""} onChange={(e) => setForm({ ...form, idade: Number(e.target.value) })} className="h-10 bg-input border-border-strong" />
                  </Campo>
                  <Campo label="Número de WhatsApp" className="col-span-2">
                    <Input
                      value={formatarTelefoneBR(numeroDigitos)}
                      placeholder="(21) 98765-4321"
                      onChange={(e) => setNumeroDigitos(extrairDigitosTelefone(e.target.value))}
                      className="h-10 bg-input border-border-strong"
                    />
                  </Campo>
                  <Campo label="Idiomas">
                    <Input value={idiomasInput} placeholder="pt-BR, en-US" onChange={(e) => setIdiomasInput(e.target.value)} className="h-10 bg-input border-border-strong" />
                  </Campo>
                  <Campo label="Perfil físico">
                    <select
                      value={form.tipo_fisico ?? ""}
                      onChange={(e) => setForm({ ...form, tipo_fisico: (e.target.value as PerfilFisico) || null })}
                      className="h-10 rounded-md border border-border-strong bg-input px-3 text-sm normal-case tracking-normal text-text-primary"
                    >
                      <option value="">Não classificada</option>
                      {PERFIS_FISICOS.map((slug) => (
                        <option key={slug} value={slug}>
                          {PERFIL_FISICO_LABEL[slug]}
                        </option>
                      ))}
                    </select>
                  </Campo>
                </div>
              </section>
              <Separator />
              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-text-brand">Atende em</h3>
                <TipoChecks
                  value={form.tipo_atendimento_aceito}
                  onChange={(tipo_atendimento_aceito) => setForm({ ...form, tipo_atendimento_aceito })}
                />
              </section>
            </div>
            {tentou && !valido && (
              <p className="mt-4 text-sm text-state-lost">Preencha nome, idade, número com DDD, idioma e pelo menos uma opção de atendimento.</p>
            )}
            <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
              <Button variant="ghost" onClick={() => handleOpenChange(false)} disabled={submitting}>Cancelar</Button>
              <Button variant="primary" onClick={submit} disabled={submitting}>
                {submitting && <Loader2 className="animate-spin" />}
                Criar modelo
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="absolute right-4 top-4">
              <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
            </div>
            <ConectarWhatsappConteudo
              nome={nomeCriado}
              qr={qr ?? null}
              status={qrStatus ?? "loading"}
              error={qrError ?? null}
              onAtualizar={() => onAtualizar?.()}
              onFechar={() => handleOpenChange(false)}
              textoFechar="Concluir"
            />
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Campo({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`grid gap-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-text-secondary ${className ?? ""}`}>
      <span className="leading-none">{label}</span>
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
  const opcoes: { tipo: TipoAtendimento; titulo: string; descricao: string }[] = [
    { tipo: "interno", titulo: "No local dela", descricao: "Cliente vai até a modelo" },
    { tipo: "externo", titulo: "No local do cliente", descricao: "Modelo se desloca" },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {opcoes.map(({ tipo, titulo, descricao }) => {
        const ativo = value.includes(tipo)
        return (
          <label
            key={tipo}
            aria-checked={ativo}
            className="group relative flex cursor-pointer items-start gap-3 rounded-md border border-input bg-input p-3.5 text-sm normal-case tracking-normal text-text-secondary transition-colors hover:border-border-strong has-[:focus-visible]:border-ring has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 aria-checked:border-gold-500 aria-checked:bg-card aria-checked:text-text-primary"
          >
            <input
              type="checkbox"
              checked={ativo}
              onChange={() => toggle(tipo)}
              className="sr-only"
            />
            <span
              aria-hidden
              className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-sm border border-border bg-surface group-aria-checked:border-gold-500 group-aria-checked:bg-gold-500"
            >
              <svg
                viewBox="0 0 12 12"
                className="size-3 text-on-brand opacity-0 group-aria-checked:opacity-100"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M2.5 6.5 5 9l4.5-5" />
              </svg>
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="font-medium text-text-primary group-aria-checked:text-text-brand">{titulo}</span>
              <span className="text-xs text-text-muted">{descricao}</span>
            </span>
          </label>
        )
      })}
    </div>
  )
}
