"use client"

import { useState } from "react"
import { Bot } from "lucide-react"

import { useObservabilidade } from "@/hooks/useObservabilidade"
import { ListaTurnos } from "@/components/observabilidade/ListaTurnos"
import { DialogAvaliar } from "@/components/observabilidade/DialogAvaliar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { PageHeader } from "@/components/layout/PageHeader"
import { cn } from "@/lib/utils"
import type { TurnoObservabilidade } from "@/tipos/observabilidade"

export default function ObservabilidadePage() {
  const [apenasNaoAvaliadas, setApenasNaoAvaliadas] = useState(false)
  const { items, nextCursor, status, error, carregarMais, avaliar, recarregar } =
    useObservabilidade({ apenasNaoAvaliadas })
  const [alvo, setAlvo] = useState<TurnoObservabilidade | null>(null)

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Observabilidade"
        description="Cada resposta do agente, avaliada por você — vira o gabarito que mede se a IA substitui o vendedor."
      />

      <section aria-label="Respostas do agente" className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
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
            <ListaTurnos turnos={items} onAvaliar={setAlvo} />
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

      {alvo && (
        <DialogAvaliar
          key={alvo.resposta_ia_id}
          turno={alvo}
          onClose={() => setAlvo(null)}
          onAvaliar={avaliar}
        />
      )}
    </div>
  )
}
