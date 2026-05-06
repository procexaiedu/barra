"use client"

import { useRouter } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatBRL } from "@/lib/formatters"
import type { AtendimentoAberto as AtendimentoAbertoTipo } from "@/tipos/clientes"
import { badgeForEstado, estadoAtendimentoLabel } from "@/components/clientes/utils"
import { tipoLabel, urgenciaLabel } from "@/components/atendimentos/utils"

export function AtendimentoAberto({ atendimento }: { atendimento: AtendimentoAbertoTipo | null }) {
  const router = useRouter()

  const ativo = atendimento !== null
  return (
    <section
      aria-label="Atendimento aberto"
      className={
        ativo
          ? "rounded-lg border border-border border-l-3 border-l-state-handoff bg-card p-5"
          : "rounded-lg border border-border bg-card p-5"
      }
    >
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        Atendimento aberto
      </p>
      {atendimento === null ? (
        <p className="text-[13px] text-text-muted">Sem atendimento aberto nesta conversa.</p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={badgeForEstado(atendimento.estado)}>
              {estadoAtendimentoLabel[atendimento.estado]}
            </Badge>
            <span className="font-mono text-xs text-text-muted">#{atendimento.numero_curto}</span>
            {(atendimento.tipo_atendimento || atendimento.urgencia || atendimento.valor_acordado !== null) && (
              <span className="text-[13px] text-text-muted">
                ·{" "}
                {[
                  atendimento.tipo_atendimento ? tipoLabel[atendimento.tipo_atendimento] : null,
                  atendimento.urgencia ? urgenciaLabel[atendimento.urgencia] : null,
                  atendimento.valor_acordado !== null
                    ? formatBRL(Number(atendimento.valor_acordado))
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>
          {atendimento.proxima_acao_esperada && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                Próxima ação
              </p>
              <p className="text-sm text-text-primary">{atendimento.proxima_acao_esperada}</p>
            </div>
          )}
          <div>
            <Button variant="secondary" size="sm" onClick={() => router.push("/atendimentos")}>
              Abrir na Central
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
