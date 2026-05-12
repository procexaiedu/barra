"use client"

import { useState } from "react"
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
import type { Cliente, CriarClienteRequest } from "@/tipos/clientes"

interface ModalCriarClienteProps {
  open: boolean
  onClose: () => void
  onCriar: (payload: CriarClienteRequest) => Promise<Cliente>
  onCriado?: (cliente: Cliente) => void
}

export function ModalCriarCliente({
  open,
  onClose,
  onCriar,
  onCriado,
}: ModalCriarClienteProps) {
  const [nome, setNome] = useState("")
  const [telefone, setTelefone] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const telefoneNormalizado = normalizarTelefoneE164(telefone)
  const podeSalvar = telefoneNormalizado !== null && !submitting

  const reset = () => {
    setNome("")
    setTelefone("")
    setSubmitting(false)
  }

  const handleClose = () => {
    if (submitting) return
    reset()
    onClose()
  }

  const handleSubmit = async () => {
    if (!telefoneNormalizado) return
    setSubmitting(true)
    try {
      const payload: CriarClienteRequest = {
        telefone: telefoneNormalizado,
        nome: nome.trim() || null,
      }
      const cliente = await onCriar(payload)
      toast.success("Cliente criado")
      onCriado?.(cliente)
      reset()
      onClose()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail === "telefone_duplicado") {
        toast.error("Telefone já cadastrado")
      } else {
        toast.error(e instanceof Error ? e.message : "Erro ao criar cliente")
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
      <DialogContent className="w-full max-w-md rounded-lg border border-border bg-popover p-6 text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <DialogTitle>Novo cliente</DialogTitle>
        <DialogDescription className="mt-1">
          Cadastre nome (opcional) e telefone no formato brasileiro.
        </DialogDescription>

        <div className="mt-5 space-y-4">
          <div>
            <Label htmlFor="novo-cliente-nome">Nome</Label>
            <Input
              id="novo-cliente-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              placeholder="Opcional"
              className="mt-2 h-10"
              disabled={submitting}
              autoComplete="off"
            />
          </div>
          <div>
            <Label htmlFor="novo-cliente-telefone">Telefone</Label>
            <Input
              id="novo-cliente-telefone"
              value={telefone}
              onChange={(e) => setTelefone(aplicarMascaraTelefone(e.target.value))}
              placeholder="(11) 99999-9999"
              className="mt-2 h-10"
              disabled={submitting}
              autoComplete="off"
              inputMode="numeric"
            />
            {telefone.length > 0 && telefoneNormalizado === null && (
              <p className="mt-1 text-xs text-state-lost">
                Telefone incompleto. Use 10 ou 11 dígitos.
              </p>
            )}
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!podeSalvar}>
            {submitting && <Loader2 className="animate-spin" />}
            Criar cliente
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
