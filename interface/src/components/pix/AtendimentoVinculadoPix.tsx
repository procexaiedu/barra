"use client"

import { Eye } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import { tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"
import { cn } from "@/lib/utils"
import type { AtendimentoResumoPix } from "@/tipos/pix"
import {
  badgeForEstadoAtendimento,
  estadoAtendimentoLabel,
  isAtendimentoTerminal,
} from "./utils"

export function AtendimentoVinculadoPix({
  atendimento,
  onVisualizar,
}: {
  atendimento: AtendimentoResumoPix | null
  onVisualizar?: () => void
}) {
  if (atendimento === null) {
    return (
      <section className="rounded-lg bg-card p-3 ring-1 ring-foreground/10">
        <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          Atendimento vinculado
        </h3>
        <p className="mt-2 text-[13px] text-text-muted">
          Pix sem atendimento vinculado.
        </p>
      </section>
    )
  }

  const terminal = isAtendimentoTerminal(atendimento.estado)
  const meta = [
    atendimento.tipo_atendimento ? tipoLabel[atendimento.tipo_atendimento] : null,
    atendimento.urgencia ? urgenciaLabel[atendimento.urgencia] : null,
    atendimento.valor_acordado !== null ? formatBRL(atendimento.valor_acordado) : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <section
      className={cn(
        "rounded-lg border-l-3 bg-card p-3 ring-1 ring-foreground/10",
        terminal ? "border-l-border-strong" : "border-l-state-handoff"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          Atendimento vinculado
        </h3>
        {onVisualizar && (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Ver atendimento"
            onClick={onVisualizar}
          >
            <Eye className="h-4 w-4" />
          </Button>
        )}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Badge variant={badgeForEstadoAtendimento(atendimento.estado)}>
          {estadoAtendimentoLabel[atendimento.estado] ?? atendimento.estado}
        </Badge>
      </div>
      <p className="mt-2 text-[13px] text-text-muted">{meta}</p>
    </section>
  )
}
