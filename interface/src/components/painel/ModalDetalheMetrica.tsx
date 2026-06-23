"use client"

import type { ReactNode } from "react"
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold text-text-primary">
            {titulo}
            {!loading && count !== undefined && (
              <span className="ml-1 font-mono tabular-nums text-text-muted">
                ({count})
              </span>
            )}
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="min-h-[120px]">
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
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" size="lg" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
