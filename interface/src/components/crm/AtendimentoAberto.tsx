"use client"

import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import type { AtendimentoAberto as AtendimentoAbertoTipo } from "@/tipos/crm"
import { badgeForEstado, estadoAtendimentoLabel } from "@/components/crm/utils"

export function AtendimentoAberto({ atendimento }: { atendimento: AtendimentoAbertoTipo | null }) {
  const router = useRouter()

  const ativo = atendimento !== null
  return (
    <section
      aria-label="Atendimento aberto"
      className={
        ativo
          ? "rounded-lg border border-border border-l-3 border-l-state-handoff bg-card p-6"
          : "rounded-lg border border-border bg-card p-6"
      }
    >
      <h2 className="mb-3 text-base font-semibold text-text-primary">Atendimento aberto</h2>
      {atendimento === null ? (
        <p className="text-[13px] text-text-muted">Sem atendimento aberto nesta conversa.</p>
      ) : (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={badgeForEstado(atendimento.estado)}>
              {estadoAtendimentoLabel[atendimento.estado]}
            </Badge>
            <span className="font-mono text-xs text-text-muted">#{atendimento.numero_curto}</span>
          </div>
          {(atendimento.tipo_atendimento || atendimento.urgencia || atendimento.valor_acordado !== null) && (
            <p className="mt-2 text-[13px] text-text-muted">
              {[
                atendimento.tipo_atendimento,
                atendimento.urgencia,
                atendimento.valor_acordado !== null
                  ? formatBRL(Number(atendimento.valor_acordado))
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {atendimento.proxima_acao_esperada && (
            <p className="mt-2 text-sm text-text-primary">
              <span className="text-text-muted">Próxima ação esperada: </span>
              {atendimento.proxima_acao_esperada}
            </p>
          )}
          <div className="mt-4">
            <Button variant="secondary" size="sm" onClick={() => router.push("/atendimentos")}>
              Abrir na Central
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
