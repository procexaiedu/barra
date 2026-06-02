"use client"

import { formatData, formatDataHora } from "@/lib/formatters"
import type { ConversaResumo } from "@/tipos/clientes"
import { direcaoLabel, motivoPerdaLabel } from "@/components/clientes/utils"

export function DadosConversa({ conversa }: { conversa: ConversaResumo }) {
  return (
    <div
      aria-label="Dados da conversa"
      className="grid grid-cols-3 divide-x divide-border rounded-lg border border-border bg-card"
    >
      <InfoCell label="Conversa desde">
        <span className="text-sm font-medium text-text-primary">
          {formatData(conversa.created_at)}
        </span>
      </InfoCell>
      <InfoCell label="Último motivo de perda">
        <span className="text-sm font-medium text-text-primary">
          {conversa.ultimo_motivo_perda
            ? motivoPerdaLabel[conversa.ultimo_motivo_perda]
            : "—"}
        </span>
      </InfoCell>
      <InfoCell label="Última mensagem">
        {conversa.ultima_mensagem_em ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-primary">
              {formatDataHora(conversa.ultima_mensagem_em)}
            </span>
            {conversa.ultima_mensagem_direcao && (
              <span className="rounded-full bg-accent px-2 py-0.5 font-mono text-[11px] text-text-muted">
                {direcaoLabel[conversa.ultima_mensagem_direcao]}
              </span>
            )}
          </div>
        ) : (
          <span className="text-sm text-text-muted">—</span>
        )}
      </InfoCell>
    </div>
  )
}

function InfoCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {label}
      </span>
      {children}
    </div>
  )
}
