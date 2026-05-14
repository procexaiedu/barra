"use client"

import { Check, Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { BannerErro } from "@/components/layout/BannerErro"
import type { ConectarWhatsappResponse } from "@/tipos/modelos"

export type QrModalStatus = "loading" | "aguardando_scan" | "conectado" | "erro"

export function ConectarWhatsappConteudo({
  nome,
  qr,
  status,
  error,
  onAtualizar,
  onFechar,
  textoFechar = "Fechar",
}: {
  nome: string
  qr: ConectarWhatsappResponse | null
  status: QrModalStatus
  error: string | null
  onAtualizar: () => void
  onFechar: () => void
  textoFechar?: string
}) {
  const src = qr?.qr_code?.startsWith("data:")
    ? qr.qr_code
    : qr?.qr_code
      ? `data:image/png;base64,${qr.qr_code}`
      : null

  return (
    <>
      <div className="mb-5">
        <DialogTitle className="text-lg font-semibold">Conectar WhatsApp de {nome}</DialogTitle>
        <DialogDescription>
          {status === "conectado"
            ? "Pareamento concluído."
            : "Escaneie o QR code no WhatsApp da modelo para ativar o número no painel."}
        </DialogDescription>
      </div>
      <div className="flex min-h-72 items-center justify-center rounded-lg border border-border bg-muted">
        {status === "loading" ? (
          <Loader2 className="animate-spin text-text-muted" size={28} strokeWidth={1.5} />
        ) : status === "erro" ? (
          <div className="w-full max-w-sm">
            <BannerErro mensagem={error ?? "QR code expirou."} onRetry={onAtualizar} />
          </div>
        ) : status === "conectado" ? (
          <div className="flex flex-col items-center gap-3 text-sm text-text-secondary">
            <Check className="text-state-closed" size={32} strokeWidth={1.5} />
            <span>WhatsApp conectado.</span>
          </div>
        ) : src ? (
          // QR code é data URI base64; next/image não otimiza esse caso.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt="QR code do WhatsApp" className="size-64" />
        ) : (
          <p className="text-sm text-text-muted">QR indisponível. Atualize para tentar novamente.</p>
        )}
      </div>
      <p className="mt-4 text-sm text-text-muted">
        {status === "aguardando_scan"
          ? "Aguardando você escanear no celular. A tela fecha sozinha quando o número estiver conectado."
          : status === "conectado"
            ? "Pronto. Esta janela fechará em instantes."
            : "A tela fecha sozinha quando o número estiver conectado."}
      </p>
      <div className="mt-6 flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="ghost" onClick={onFechar}>{textoFechar}</Button>
        <Button
          variant="secondary"
          onClick={onAtualizar}
          disabled={status === "loading" || status === "conectado"}
        >
          <RefreshCw size={16} strokeWidth={1.5} />
          Atualizar QR
        </Button>
      </div>
    </>
  )
}
