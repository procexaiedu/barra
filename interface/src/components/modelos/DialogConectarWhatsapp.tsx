"use client"

import { Loader2, RefreshCw, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { BannerErro } from "@/components/layout/BannerErro"
import type { ConectarWhatsappResponse, ModeloDetalhe } from "@/tipos/modelos"

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
  status: "idle" | "loading" | "success" | "error"
  error: string | null
  onOpenChange: (open: boolean) => void
  onAtualizar: () => void
}) {
  const src = qr?.qr_code?.startsWith("data:")
    ? qr.qr_code
    : qr?.qr_code
      ? `data:image/png;base64,${qr.qr_code}`
      : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-lg rounded-lg border border-border bg-popover p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <DialogTitle className="text-lg font-semibold">Conectar WhatsApp de {modelo?.nome}</DialogTitle>
            <DialogDescription>Escaneie o QR code no WhatsApp da modelo para ativar o numero no painel.</DialogDescription>
          </div>
          <DialogClose render={<Button variant="ghost" size="icon" aria-label="Fechar"><X size={18} strokeWidth={1.5} /></Button>} />
        </div>
        <div className="flex min-h-72 items-center justify-center rounded-lg border border-border bg-ink-100">
          {status === "loading" ? (
            <Loader2 className="animate-spin text-text-muted" size={28} strokeWidth={1.5} />
          ) : status === "error" ? (
            <div className="w-full max-w-sm">
              <BannerErro mensagem={error ?? "QR code expirou."} onRetry={onAtualizar} />
            </div>
          ) : src ? (
            <img src={src} alt="QR code do WhatsApp" className="size-64" />
          ) : (
            <p className="text-sm text-text-muted">QR indisponivel. Atualize para tentar novamente.</p>
          )}
        </div>
        <p className="mt-4 text-sm text-text-muted">A tela fecha sozinha quando o numero estiver conectado.</p>
        <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Fechar</Button>
          <Button variant="secondary" onClick={onAtualizar} disabled={status === "loading"}>
            <RefreshCw size={16} strokeWidth={1.5} />
            Atualizar QR
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
