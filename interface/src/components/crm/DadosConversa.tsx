"use client"

import { RefreshCw } from "lucide-react"
import { formatData, formatDataHora } from "@/lib/formatters"
import type { ConversaResumo } from "@/tipos/crm"
import { direcaoLabel, motivoPerdaLabel } from "@/components/crm/utils"

export function DadosConversa({ conversa }: { conversa: ConversaResumo }) {
  return (
    <section
      aria-label="Dados da conversa"
      className="rounded-lg border border-border bg-card p-6"
    >
      <h2 className="mb-4 text-base font-semibold text-text-primary">Dados da conversa</h2>
      <dl className="space-y-3">
        <Linha rotulo="Recorrência">
          <span className="inline-flex items-center gap-2 text-sm text-text-primary">
            {conversa.recorrente ? (
              <>
                <RefreshCw size={16} strokeWidth={1.5} className="text-text-muted" />
                Recorrente
              </>
            ) : (
              "Nova"
            )}
          </span>
        </Linha>
        <Linha rotulo="Último motivo de perda">
          <span className="text-sm text-text-primary">
            {conversa.ultimo_motivo_perda
              ? motivoPerdaLabel[conversa.ultimo_motivo_perda]
              : "Nenhum"}
          </span>
        </Linha>
        <Linha rotulo="Última mensagem">
          {conversa.ultima_mensagem_em ? (
            <span className="inline-flex flex-wrap items-center gap-2 text-sm text-text-primary">
              {formatDataHora(conversa.ultima_mensagem_em)}
              {conversa.ultima_mensagem_direcao && (
                <span className="rounded-full bg-ink-300 px-2 py-0.5 font-mono text-[11px] text-text-muted">
                  {direcaoLabel[conversa.ultima_mensagem_direcao]}
                </span>
              )}
            </span>
          ) : (
            <span className="text-sm text-text-primary">Sem mensagens ainda</span>
          )}
        </Linha>
        <Linha rotulo="Conversa desde">
          <span className="text-sm text-text-primary">{formatData(conversa.created_at)}</span>
        </Linha>
      </dl>
    </section>
  )
}

function Linha({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <dt className="min-w-[200px] text-xs font-medium text-text-muted">{rotulo}</dt>
      <dd>{children}</dd>
    </div>
  )
}
