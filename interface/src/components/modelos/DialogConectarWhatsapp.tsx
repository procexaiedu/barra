"use client"

import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog"
import { ConectarWhatsappConteudo, type QrModalStatus } from "@/components/modelos/ConectarWhatsappConteudo"
import type { ConectarWhatsappResponse, ModeloDetalhe } from "@/tipos/modelos"

export type { QrModalStatus }

export function DialogConectarWhatsapp({
  open,
  modelo,
  qr,
  status,
  error,
  onOpenChange,
  onAtualizar,
}: {
  open: boolean
  modelo: ModeloDetalhe | null
  qr: ConectarWhatsappResponse | null
  status: QrModalStatus
  error: string | null
  onOpenChange: (open: boolean) => void
  onAtualizar: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-lg rounded-lg border border-border bg-popover p-6">
        <div className="absolute right-4 top-4">
          <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
        </div>
        <ConectarWhatsappConteudo
          nome={modelo?.nome ?? ""}
          qr={qr}
          status={status}
          error={error}
          onAtualizar={onAtualizar}
          onFechar={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  )
}
