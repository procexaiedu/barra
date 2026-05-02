"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import type { DashboardEscaladasResponse } from "@/tipos/dashboard"
import { cn } from "@/lib/utils"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  data: DashboardEscaladasResponse | null
  status: "idle" | "loading" | "success" | "error"
  error: string | null
  onLoad: () => void
  onReset: () => void
}

export function DialogTodasEscaladas({
  open,
  onOpenChange,
  data,
  status,
  error,
  onLoad,
  onReset,
}: Props) {
  const router = useRouter()

  useEffect(() => {
    if (open && status === "idle") {
      onLoad()
    }
    if (!open) {
      onReset()
    }
  }, [open, status, onLoad, onReset])

  const navegarParaMotivo = (motivo: string) => {
    onOpenChange(false)
    router.push(
      `/atendimentos?ia_pausada=true&motivo_escalada=${encodeURIComponent(motivo)}`
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-full max-w-lg flex-col gap-5 rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold text-text-primary">
          Motivos de escalada — período completo
        </DialogTitle>

        <div className="max-h-[60vh] min-h-[120px] overflow-y-auto pr-1">
          {status === "loading" ? (
            <ul className="flex flex-col gap-2">
              {Array.from({ length: 8 }).map((_, idx) => (
                <li key={idx}>
                  <Skeleton className="h-7 w-full rounded-md" />
                </li>
              ))}
            </ul>
          ) : status === "error" ? (
            <BannerErro mensagem={error ?? undefined} onRetry={onLoad} />
          ) : status === "success" && data ? (
            data.motivos.length === 0 ? (
              <p className="text-sm text-text-muted">Sem atendimentos escalados no período.</p>
            ) : (
              <ul className="flex flex-col">
                {data.motivos.map((linha) => (
                  <li key={linha.motivo}>
                    <button
                      type="button"
                      onClick={() => navegarParaMotivo(linha.motivo)}
                      className={cn(
                        "grid h-7 w-full grid-cols-[1fr_40px] items-center gap-3 rounded-md text-left",
                        "transition-colors hover:bg-ink-200",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      )}
                    >
                      <span className="truncate pl-1 text-[13px] text-text-primary">
                        {linha.motivo}
                      </span>
                      <span className="text-right font-mono text-xs font-medium text-text-primary">
                        {linha.contagem}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
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
