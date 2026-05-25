"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError } from "@/lib/api"
import {
  aplicarMascaraTelefone,
  normalizarTelefoneE164,
} from "@/components/clientes/utils"
import { SeletorPerfis } from "@/components/clientes/SeletorPerfis"
import { formatTelefone } from "@/lib/formatters"
import type { Cliente, EditarClienteRequest, PerfilFisico } from "@/tipos/clientes"

interface ModalEditarClienteProps {
  open: boolean
  clienteId: string
  nomeAtual: string | null
  telefoneAtual: string
  perfisAtuais: PerfilFisico[]
  onClose: () => void
  onSalvar: (id: string, payload: EditarClienteRequest) => Promise<Cliente>
}

export function ModalEditarCliente({
  open,
  clienteId,
  nomeAtual,
  telefoneAtual,
  perfisAtuais,
  onClose,
  onSalvar,
}: ModalEditarClienteProps) {
  const [nome, setNome] = useState(nomeAtual ?? "")
  const [telefone, setTelefone] = useState(() =>
    aplicarMascaraTelefone(formatTelefone(telefoneAtual))
  )
  const [perfis, setPerfis] = useState<PerfilFisico[]>(perfisAtuais)
  const [submitting, setSubmitting] = useState(false)
  const nomeInputRef = useRef<HTMLInputElement>(null)

  const telefoneNormalizado = normalizarTelefoneE164(telefone)
  const nomeOriginal = (nomeAtual ?? "").trim()
  const perfisOriginais = [...perfisAtuais].sort().join(",")
  const perfisMudaram = [...perfis].sort().join(",") !== perfisOriginais
  const houveMudanca =
    nome.trim() !== nomeOriginal || telefoneNormalizado !== telefoneAtual || perfisMudaram
  const podeSalvar =
    telefoneNormalizado !== null && !submitting && houveMudanca

  useEffect(() => {
    if (!open) return
    const handle = requestAnimationFrame(() => {
      const input = nomeInputRef.current
      if (!input) return
      input.focus()
      if (input.value.length > 0) input.select()
    })
    return () => cancelAnimationFrame(handle)
  }, [open])

  const handleClose = () => {
    if (submitting) return
    onClose()
  }

  const handleSubmit = async () => {
    if (!telefoneNormalizado) return
    setSubmitting(true)
    try {
      const payload: EditarClienteRequest = {
        nome: nome.trim() || null,
        telefone: telefoneNormalizado,
        perfis_preferidos: perfis,
      }
      await onSalvar(clienteId, payload)
      toast.success("Cliente atualizado")
      onClose()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail === "telefone_duplicado") {
        toast.error("Telefone já cadastrado")
      } else {
        toast.error(e instanceof Error ? e.message : "Erro ao atualizar cliente")
      }
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) handleClose()
      }}
    >
      <DialogContent className="w-full max-w-lg rounded-lg border border-border bg-popover p-6 text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <DialogTitle>Editar cliente</DialogTitle>
        <DialogDescription className="mt-1">
          Os valores atuais estão pré-carregados — apague e digite para alterar.
        </DialogDescription>

        <div className="mt-5 space-y-4">
          <div>
            <Label htmlFor="editar-cliente-nome">Nome</Label>
            <Input
              ref={nomeInputRef}
              id="editar-cliente-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Opcional"
              className="mt-2 h-10"
              disabled={submitting}
              autoComplete="off"
            />
            <p className="mt-1 text-xs text-text-muted">
              Atual: {nomeOriginal.length > 0 ? nomeOriginal : "sem nome"}.
            </p>
          </div>
          <div>
            <Label htmlFor="editar-cliente-telefone">Telefone</Label>
            <Input
              id="editar-cliente-telefone"
              value={telefone}
              onChange={(e) => setTelefone(aplicarMascaraTelefone(e.target.value))}
              placeholder="(11) 99999-9999"
              className="mt-2 h-10"
              disabled={submitting}
              autoComplete="off"
              inputMode="numeric"
            />
            {telefone.length > 0 && telefoneNormalizado === null ? (
              <p className="mt-1 text-xs text-state-lost">
                Telefone incompleto. Use 10 ou 11 dígitos.
              </p>
            ) : (
              <p className="mt-1 text-xs text-text-muted">
                Atual: {formatTelefone(telefoneAtual)}.
              </p>
            )}
          </div>
          <div>
            <Label>Perfil físico preferido</Label>
            <p className="mt-1 mb-2 text-xs text-text-muted">
              Pode marcar mais de um.
            </p>
            <SeletorPerfis
              value={perfis}
              onChange={setPerfis}
              disabled={submitting}
              idPrefix="editar-cliente-perfil"
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!podeSalvar}>
            {submitting && <Loader2 className="animate-spin" />}
            Salvar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
