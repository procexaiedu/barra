"use client"

import { Dialog, DialogBody, DialogCloseButton, DialogContent } from "@/components/ui/dialog"
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
      <DialogContent size="sm">
        <div className="absolute right-4 top-4">
          <DialogCloseButton />
        </div>
        <DialogBody>
          <ConectarWhatsappConteudo
            nome={modelo?.nome ?? ""}
            qr={qr}
            status={status}
            error={error}
            onAtualizar={onAtualizar}
            onFechar={() => onOpenChange(false)}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
