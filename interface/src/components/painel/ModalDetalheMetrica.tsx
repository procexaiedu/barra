"use client"

import type { ReactNode } from "react"
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog"
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
      <DialogContent className="flex w-[min(96vw,80rem)] max-h-[92vh] min-h-[60vh] flex-col rounded-xl bg-card p-0 shadow-xl ring-1 ring-border">
        <header className="border-b border-border px-8 py-4">
          <DialogTitle className="text-base font-semibold text-text-primary">
            {tituloCompleto}
          </DialogTitle>
        </header>

        <div className="flex-1 min-h-[120px] overflow-y-auto px-8 py-6">
          {loading ? (
            <ul className="flex flex-col gap-2">
              {Array.from({ length: 8 }).map((_, idx) => (
                <li key={idx}>
                  <Skeleton className="h-8 w-full rounded-md" />
                </li>
              ))}
            </ul>
          ) : error ? (
            <BannerErro mensagem={error} onRetry={onRetry} />
          ) : (
            children
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
