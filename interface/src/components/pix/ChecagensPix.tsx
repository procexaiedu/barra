"use client"

import { CheckCircle2, XCircle } from "lucide-react"
import type { ChecagemPix } from "@/tipos/pix"
import { checagemLabel } from "./utils"

export function ChecagensPix({ checagens }: { checagens: ChecagemPix[] }) {
  return (
    <section
      aria-label="Checagens automáticas"
      className="rounded-lg border border-border bg-card p-5"
    >
      <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Checagens automáticas
      </h3>
      {checagens.length === 0 ? (
        <p className="mt-3 text-[13px] text-text-muted">
          Nenhuma checagem registrada para este Pix.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {checagens.map((c) => (
            <li key={c.chave} className="flex items-start gap-3">
              {c.passou ? (
                <CheckCircle2
                  size={16}
                  strokeWidth={1.5}
                  className="mt-0.5 text-state-closed"
                  aria-label="passou"
                />
              ) : (
                <XCircle
                  size={16}
                  strokeWidth={1.5}
                  className="mt-0.5 text-state-lost"
                  aria-label="falhou"
                />
              )}
              <div className="flex-1">
                <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-primary">
                  {checagemLabel(c)}
                </p>
                {!c.passou && c.motivo && (
                  <p className="mt-1 text-[13px] text-text-muted">{c.motivo}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
