"use client"

import { useState } from "react"
import { Bot } from "lucide-react"

import { useObservabilidade, type OrigemTurnos } from "@/hooks/useObservabilidade"
import { ListaConversas } from "@/components/observabilidade/ListaConversas"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { cn } from "@/lib/utils"

/** Tela de Avaliação ("Avaliar ao vivo"): cada resposta do agente no tráfego
 *  real (ou e2e), agrupada por conversa em chat e avaliada inline por Fernando
 *  (bom/ruim + nota + comentário). Ground-truth contínuo, single-rater. */
export function PainelObservabilidade() {
  const [apenasNaoAvaliadas, setApenasNaoAvaliadas] = useState(false)
  const [origem, setOrigem] = useState<OrigemTurnos>("prod")
  const { items, nextCursor, status, error, carregarMais, avaliar, recarregar } =
    useObservabilidade({ apenasNaoAvaliadas, origem })

  return (
    <>
      <section aria-label="Respostas do agente" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-lg border border-border p-0.5">
            {(["prod", "e2e"] as const).map((o) => (
              <button
                key={o}
                type="button"
                onClick={() => setOrigem(o)}
                aria-pressed={origem === o}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-150",
                  origem === o
                    ? "bg-accent text-text-brand"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                {o === "prod" ? "Produção" : "E2E"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setApenasNaoAvaliadas((v) => !v)}
            aria-pressed={apenasNaoAvaliadas}
            className={cn(
              "rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all duration-150",
              apenasNaoAvaliadas
                ? "border-border-brand bg-accent text-text-brand"
                : "border-border text-text-muted hover:text-text-primary",
            )}
          >
            Só não avaliadas
          </button>
          {status === "success" && (
            <span className="ml-auto text-xs font-medium tabular-nums text-text-muted">
              {items.length} {items.length === 1 ? "resposta" : "respostas"}
            </span>
          )}
        </div>

        {status === "loading" && (
          <div aria-busy="true" className="flex flex-col gap-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[92px] rounded-lg" />
            ))}
          </div>
        )}

        {status === "error" && (
          <BannerErro mensagem={error ?? undefined} onRetry={() => void recarregar()} />
        )}

        {status === "success" && items.length === 0 && (
          <Card>
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
                <Bot size={22} strokeWidth={1.75} className="text-text-muted" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">
                  Nenhuma resposta do agente ainda.
                </p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Quando a IA responder um cliente, aparece aqui para você avaliar.
                </p>
              </div>
            </div>
          </Card>
        )}

        {status === "success" && items.length > 0 && (
          <>
            <ListaConversas turnos={items} onAvaliar={avaliar} />
            {nextCursor && (
              <div className="flex justify-center">
                <Button variant="outline" onClick={carregarMais}>
                  Carregar mais
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </>
  )
}
