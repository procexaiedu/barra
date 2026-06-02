"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { CheckCircle2 } from "lucide-react"

import { api } from "@/lib/api"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { ATOR_LABEL, PRIORIDADE_BAR, PRIORIDADE_LABEL } from "@/lib/tarefas"
import type { Tarefa, TarefasListaResponse } from "@/tipos/tarefas"

/** Widget autocontido da seção "Hoje" do Painel: tarefas com prazo hoje ainda
 *  pendentes (não-`feita`). Faz o próprio fetch — não acopla ao backend do painel. */
export function TarefasHojeWidget() {
  const [tarefas, setTarefas] = useState<Tarefa[] | null>(null)

  useEffect(() => {
    void api<TarefasListaResponse>("/v1/tarefas?prazo=hoje")
      .then((r) => setTarefas(r.items.filter((t) => t.status !== "feita")))
      .catch(() => setTarefas([]))
  }, [])

  if (tarefas === null) return null // silencioso no carregamento

  return (
    <section aria-label="Tarefas de hoje" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Tarefas de hoje
        </h2>
        <Link
          href="/tarefas"
          className="rounded-md text-xs font-medium text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Ver todas
        </Link>
      </div>

      {tarefas.length === 0 ? (
        <Card>
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
            <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
              <CheckCircle2 size={22} strokeWidth={1.75} className="text-text-muted" />
            </div>
            <div>
              <p className="text-sm font-medium text-text-primary">Nenhuma tarefa para hoje.</p>
              <p className="mt-1 text-[13px] text-text-muted">Tarefas com prazo de hoje aparecem aqui.</p>
            </div>
          </div>
        </Card>
      ) : (
        <Card className="gap-0 py-0">
          {tarefas.map((t, i) => (
            <Link
              key={t.id}
              href="/tarefas"
              className={cn(
                "flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                i > 0 && "border-t border-border-subtle",
              )}
            >
              <span className={cn("size-1.5 shrink-0 rounded-full", PRIORIDADE_BAR[t.prioridade])} />
              <span className="flex-1 truncate text-sm text-text-primary">{t.titulo}</span>
              <span className="shrink-0 text-xs text-text-muted">
                {PRIORIDADE_LABEL[t.prioridade]}
                {t.atribuido && ` · ${t.atribuido.nome ?? ATOR_LABEL[t.atribuido.tipo]}`}
              </span>
            </Link>
          ))}
        </Card>
      )}
    </section>
  )
}
