"use client"

import { ExternalLink, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
} from "@/components/ui/dialog"
import { BannerErro } from "@/components/layout/BannerErro"
import type { ComprovanteUrlResponse, PixDetalhe } from "@/tipos/pix"

export function DialogVisualizarComprovante({
  open,
  onOpenChange,
  pix,
  comprovante,
  comprovanteStatus,
  onTentarNovamente,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  pix: PixDetalhe | null
  comprovante: ComprovanteUrlResponse | null
  comprovanteStatus: "idle" | "loading" | "success" | "error"
  onTentarNovamente: () => void
}) {
  const isPdf = pix?.mime_type === "application/pdf"
  const isImage = pix?.mime_type.startsWith("image/")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[100vh] w-[100vw] items-center justify-center bg-ink-0 p-0">
        <div className="relative flex h-full w-full items-center justify-center">
          <div className="absolute right-4 top-4 z-10">
            <DialogClose
              render={
                <Button variant="ghost" size="icon" aria-label="Fechar">
                  <X size={20} strokeWidth={1.5} />
                </Button>
              }
            />
          </div>

          {comprovanteStatus === "error" ? (
            <div className="w-full max-w-md">
              <BannerErro
                mensagem="Não foi possível carregar o comprovante."
                onRetry={onTentarNovamente}
              />
            </div>
          ) : comprovanteStatus === "loading" || comprovante === null ? (
            <p className="text-sm text-text-muted">Carregando…</p>
          ) : isImage ? (
            <img
              src={comprovante.url}
              alt={pix?.nome_arquivo ?? "Comprovante"}
              className="max-h-[90vh] max-w-[90vw] object-contain"
            />
          ) : isPdf ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-4">
              <iframe
                src={comprovante.url}
                title={pix?.nome_arquivo ?? "Comprovante"}
                className="h-[90vh] w-[90vw]"
              />
              <a
                href={comprovante.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-text-link underline-offset-4 hover:underline"
              >
                <ExternalLink size={16} strokeWidth={1.5} />
                Abrir em nova aba
              </a>
            </div>
          ) : (
            <a
              href={comprovante.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-text-link underline-offset-4 hover:underline"
            >
              <ExternalLink size={16} strokeWidth={1.5} />
              Abrir em nova aba
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
