"use client"

import {
  AlertCircle,
  CheckCircle2,
  Dot,
  Inbox,
  RefreshCw,
  XCircle,
  type LucideIcon,
} from "lucide-react"
import { formatDataHora } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { EventoPix } from "@/tipos/pix"
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

export function LinhaTempoPix({ eventos }: { eventos: EventoPix[] }) {
  return (
    <section
      aria-label="Linha do tempo do Pix"
      className="rounded-lg border border-border bg-card"
    >
      <h3 className="px-5 pt-5 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Linha do tempo
      </h3>
      {eventos.length === 0 ? (
        <p className="px-5 py-5 text-[13px] text-text-muted">
          Nenhum evento registrado.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {eventos.map((evt) => {
            const visual = eventoVisual(evt)
            const Icon = ICONS[visual.icone] ?? Dot
            const resumo =
              evt.tipo === "pix_rejeitado"
                ? formatRejeicao(evt)
                : evt.resumo

            return (
              <li
                key={evt.id}
                className="flex items-start gap-3 px-5 py-3"
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
                    <span className="text-xs text-text-muted">· {evt.autor}</span>
                    <span className="ml-auto text-xs text-text-muted">
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
      )}
    </section>
  )
}

function formatRejeicao(evt: EventoPix): string | null {
  const motivo = evt.payload?.motivo
  const observacao = evt.payload?.observacao
  const motivoStr = typeof motivo === "string" ? motivo : null
  const obsStr = typeof observacao === "string" ? observacao : null
  if (!motivoStr && !obsStr) return evt.resumo
  const parts: string[] = []
  if (motivoStr) parts.push(motivoStr)
  if (obsStr) parts.push(obsStr.length > 40 ? `${obsStr.slice(0, 40)}…` : obsStr)
  return parts.join(" · ")
}
