"use client"

import { useRouter } from "next/navigation"
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
}: {
  atendimento: AtendimentoResumoPix | null
}) {
  const router = useRouter()

  if (atendimento === null) {
    return (
      <section className="rounded-lg border border-border bg-card p-5">
        <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          Atendimento vinculado
        </h3>
        <p className="mt-3 text-[13px] text-text-muted">
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
        "rounded-lg border border-border border-l-3 bg-card p-5",
        terminal ? "border-l-border-strong" : "border-l-state-handoff"
      )}
    >
      <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Atendimento vinculado
      </h3>
      <div className="mt-3 flex items-center gap-2">
        <Badge variant={badgeForEstadoAtendimento(atendimento.estado)}>
          {estadoAtendimentoLabel[atendimento.estado] ?? atendimento.estado}
        </Badge>
        <span className="font-mono text-xs text-text-muted">
          #{atendimento.numero_curto}
        </span>
      </div>
      <p className="mt-2 text-[13px] text-text-muted">{meta}</p>
      {atendimento.proxima_acao_esperada && (
        <p className="mt-1 text-[13px] text-state-handoff">
          {atendimento.proxima_acao_esperada}
        </p>
      )}
      <div className="mt-4">
        <Button variant="ghost" size="sm" onClick={() => router.push("/atendimentos")}>
          Abrir na Central
        </Button>
      </div>
    </section>
  )
}
