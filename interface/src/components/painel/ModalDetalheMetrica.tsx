"use client"

import type { ReactNode } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"

interface Props {
  titulo: string
  count?: number
  open: boolean
  onOpenChange: (v: boolean) => void
  loading: boolean
  error: string | null
  onRetry: () => void
  children: ReactNode
}

export function ModalDetalheMetrica({
  titulo,
  count,
  open,
  onOpenChange,
  loading,
  error,
  onRetry,
  children,
}: Props) {
  const tituloCompleto =
    !loading && count !== undefined ? `${titulo} (${count})` : titulo

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-full max-w-lg flex-col gap-5 rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold text-text-primary">
          {tituloCompleto}
        </DialogTitle>

        <div className="max-h-[60vh] min-h-[80px] overflow-y-auto pr-1">
          {loading ? (
            <ul className="flex flex-col gap-2">
              {Array.from({ length: 6 }).map((_, idx) => (
                <li key={idx}>
                  <Skeleton className="h-7 w-full rounded-md" />
                </li>
              ))}
            </ul>
          ) : error ? (
            <BannerErro mensagem={error} onRetry={onRetry} />
          ) : (
            children
          )}
        </div>

        <div className="flex justify-end">
          <Button variant="ghost" size="lg" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
