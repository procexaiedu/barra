"use client"

import { useState } from "react"
import {
  AlertCircle,
  CheckCircle2,
  Dot,
  Inbox,
  RefreshCw,
  XCircle,
  type LucideIcon,
} from "lucide-react"
import { formatDataHora, formatRotulo } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { EventoPix } from "@/tipos/pix"
import { autorEventoLabel } from "@/components/atendimentos/utils"
import { Button } from "@/components/ui/button"
import { eventoVisual } from "./utils"

const ICONS: Record<string, LucideIcon> = {
  Inbox,
  CheckCircle2,
  AlertCircle,
  XCircle,
  RefreshCw,
  Dot,
}

const COR_CLASS: Record<string, string> = {
  muted: "text-text-muted",
  success: "text-state-closed",
  warn: "text-state-handoff",
  danger: "text-state-lost",
}

const LIMITE = 3

export function LinhaTempoPix({ eventos }: { eventos: EventoPix[] }) {
  const [expandido, setExpandido] = useState(false)

  const visiveis = expandido ? eventos : eventos.slice(0, LIMITE)
  const temMais = eventos.length > LIMITE

  return (
    <section
      aria-label="Histórico do Pix"
      className="rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle"
    >
      <h3 className="flex items-center gap-2 px-3 pt-3 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        <span className="h-3 w-0.5 rounded-full bg-gold-500" aria-hidden />
        Histórico
      </h3>
      {eventos.length === 0 ? (
        <p className="px-3 py-3 text-[13px] text-text-muted">
          Nenhum evento registrado.
        </p>
      ) : (
        <>
          <ul className="mt-2 divide-y divide-border">
            {visiveis.map((evt) => {
              const visual = eventoVisual(evt)
              const Icon = ICONS[visual.icone] ?? Dot
              const resumo =
                evt.tipo === "pix_rejeitado"
                  ? formatRejeicao(evt)
                  : evt.resumo

              return (
                <li
                  key={evt.id}
                  className="flex items-start gap-3 px-3 py-2"
                >
                  <Icon
                    size={16}
                    strokeWidth={1.5}
                    className={cn("mt-0.5 shrink-0", COR_CLASS[visual.cor] ?? COR_CLASS.muted)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <p className="text-sm font-medium text-text-primary">
                        {visual.label}
                      </p>
                      <span className="text-xs text-text-muted">· {autorEventoLabel(evt.autor)}</span>
                      <span className="ml-auto font-mono text-xs tabular-nums text-text-muted">
                        {formatDataHora(evt.created_at)}
                      </span>
                    </div>
                    {resumo && (
                      <p className="mt-1 truncate text-[13px] text-text-muted">
                        {resumo}
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
          {temMais && (
            <div className="border-t border-border px-3 py-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => setExpandido((v) => !v)}
              >
                {expandido ? "Recolher" : `Ver todos (${eventos.length})`}
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function formatRejeicao(evt: EventoPix): string | null {
  const motivo = evt.payload?.motivo
  const observacao = evt.payload?.observacao
  const motivoStr = typeof motivo === "string" ? formatRotulo(motivo) ?? motivo : null
  const obsStr = typeof observacao === "string" ? observacao : null
  if (!motivoStr && !obsStr) return evt.resumo
  const parts: string[] = []
  if (motivoStr) parts.push(motivoStr)
  if (obsStr) parts.push(obsStr.length > 40 ? `${obsStr.slice(0, 40)}…` : obsStr)
  return parts.join(" · ")
}
