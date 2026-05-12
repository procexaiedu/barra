"use client"

import { X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { formatBRL } from "@/lib/formatters"
import { tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"
import type { AtendimentoResumoPix } from "@/tipos/pix"
import {
  badgeForEstadoAtendimento,
  estadoAtendimentoLabel,
} from "./utils"

export function ModalAtendimentoPix({
  open,
  onOpenChange,
  atendimento,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  atendimento: AtendimentoResumoPix | null
}) {
  const meta = atendimento
    ? [
        atendimento.tipo_atendimento ? tipoLabel[atendimento.tipo_atendimento] : null,
        atendimento.urgencia ? urgenciaLabel[atendimento.urgencia] : null,
        atendimento.valor_acordado !== null ? formatBRL(atendimento.valor_acordado) : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : ""

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(90vw,420px)] rounded-lg border border-border bg-card p-5">
        <div className="flex items-start justify-between gap-3">
          <DialogTitle>Atendimento vinculado</DialogTitle>
          <DialogClose
            render={
              <Button variant="ghost" size="icon" aria-label="Fechar">
                <X className="h-4 w-4" />
              </Button>
            }
          />
        </div>
        {atendimento === null ? (
          <p className="mt-3 text-[13px] text-text-muted">
            Pix sem atendimento vinculado.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={badgeForEstadoAtendimento(atendimento.estado)}>
                {estadoAtendimentoLabel[atendimento.estado] ?? atendimento.estado}
              </Badge>
            </div>
            {meta && <p className="text-[13px] text-text-muted">{meta}</p>}
            {atendimento.proxima_acao_esperada && (
              <p className="text-[13px] text-state-handoff">
                {atendimento.proxima_acao_esperada}
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
