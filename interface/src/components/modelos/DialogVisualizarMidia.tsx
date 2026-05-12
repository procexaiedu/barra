"use client"

import { ExternalLink, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog"
import type { MidiaItem } from "@/tipos/modelos"

export function DialogVisualizarMidia({
  midia,
  onOpenChange,
}: {
  midia: MidiaItem | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={midia !== null} onOpenChange={onOpenChange}>
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
          {midia?.tipo === "video" ? (
            <video src={midia.url_assinada} controls className="max-h-[90vh] max-w-[90vw]" />
          ) : midia ? (
            // URL assinada do MinIO com expiry; next/image precisaria de loader customizado.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={midia.url_assinada} alt={midia.tag} className="max-h-[90vh] max-w-[90vw] object-contain" />
          ) : null}
          {midia && (
            <a
              href={midia.url_assinada}
              target="_blank"
              rel="noopener noreferrer"
              className="absolute bottom-4 inline-flex items-center gap-2 text-sm text-text-link underline-offset-4 hover:underline"
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
