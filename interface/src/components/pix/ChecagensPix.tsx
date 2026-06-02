"use client"

import { CheckCircle2, XCircle } from "lucide-react"
import type { ChecagemPix } from "@/tipos/pix"
import { checagemLabel } from "./utils"

export function ChecagensPix({ checagens }: { checagens: ChecagemPix[] }) {
  return (
    <section
      aria-label="Verificações automáticas"
      className="rounded-lg bg-card p-3 ring-1 ring-foreground/10"
    >
      <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Verificações automáticas
      </h3>
      {checagens.length === 0 ? (
        <p className="mt-2 text-[13px] text-text-muted">
          Nenhuma verificação registrada para este Pix.
        </p>
      ) : (
        <ul className="mt-2 space-y-2">
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
