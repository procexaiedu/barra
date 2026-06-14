"use client"

import { ThumbsDown, ThumbsUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { TurnoObservabilidade } from "@/tipos/observabilidade"

function preview(s: string, n = 140) {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

export function ListaTurnos({
  turnos,
  onAvaliar,
}: {
  turnos: TurnoObservabilidade[]
  onAvaliar: (t: TurnoObservabilidade) => void
}) {
  return (
    <div className="divide-y divide-border rounded-lg border border-border bg-card">
      {turnos.map((t) => (
        <button
          key={t.resposta_ia_id}
          type="button"
          onClick={() => onAvaliar(t)}
          className="flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors hover:bg-muted/50"
        >
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <span className="font-medium text-text-primary">{t.modelo_nome}</span>
            <span>·</span>
            <span className="truncate">{t.cliente_nome ?? t.cliente_telefone}</span>
            {t.numero_curto != null && <span>· #{t.numero_curto}</span>}
            <span className="ml-auto shrink-0 tabular-nums">
              {new Date(t.resposta_ia.created_at).toLocaleString("pt-BR")}
            </span>
          </div>
          {t.mensagem_cliente && (
            <p className="text-[13px] text-text-muted">
              <span className="font-medium">Cliente:</span> {preview(t.mensagem_cliente.conteudo)}
            </p>
          )}
          <p className="text-sm text-text-primary">
            <span className="font-medium text-text-muted">IA:</span> {preview(t.resposta_ia.conteudo)}
          </p>
          <div className="mt-0.5">
            {t.avaliacao ? (
              <Badge variant={t.avaliacao.veredito === "bom" ? "active" : "lost"}>
                {t.avaliacao.veredito === "bom" ? (
                  <ThumbsUp size={11} strokeWidth={2} />
                ) : (
                  <ThumbsDown size={11} strokeWidth={2} />
                )}
                {t.avaliacao.veredito === "bom" ? "Bom" : "Ruim"}
                {t.avaliacao.nota != null ? ` · ${t.avaliacao.nota}/5` : ""}
              </Badge>
            ) : (
              <Badge variant="info">Não avaliada</Badge>
            )}
          </div>
        </button>
      ))}
    </div>
  )
}
