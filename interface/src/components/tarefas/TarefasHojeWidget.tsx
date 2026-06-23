"use client"

import { useState } from "react"
import Link from "next/link"
import { CheckCircle2, Plus } from "lucide-react"

import { useTarefas } from "@/hooks/useTarefas"
import { DialogTarefa } from "@/components/tarefas/DialogTarefa"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ATOR_LABEL, PRIORIDADE_BAR, PRIORIDADE_LABEL } from "@/lib/tarefas"
import type { Tarefa } from "@/tipos/tarefas"

/** Widget autocontido da seção "Hoje" do Painel: tarefas com prazo hoje ainda
 *  pendentes (não-`feita`). Reusa `useTarefas` para listar/criar/editar sem
 *  acoplar ao backend do painel; o modal abre no próprio painel. */
export function TarefasHojeWidget() {
  const { tarefas, status, responsaveis, criar, atualizar } = useTarefas({
    busca: "",
    status: "todos",
    prioridade: "todas",
    prazo: "hoje",
    minhas: false,
  })
  const [dialogAberto, setDialogAberto] = useState(false)
  const [tarefaEdit, setTarefaEdit] = useState<Tarefa | null>(null)

  const abrirCriar = () => {
    setTarefaEdit(null)
    setDialogAberto(true)
  }
  const abrirEditar = (t: Tarefa) => {
    setTarefaEdit(t)
    setDialogAberto(true)
  }

  if (status !== "success") return null // silencioso no carregamento/erro

  const pendentes = tarefas.filter((t) => t.status !== "feita")

  return (
    <section aria-label="Tarefas de hoje" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
          <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
          Tarefas de hoje
          {pendentes.length > 0 && (
            <span className="font-mono text-xs tabular-nums text-text-muted">
              {pendentes.length}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={abrirCriar}>
            <Plus size={14} strokeWidth={1.5} />
            Nova
          </Button>
          <Link
            href="/tarefas"
            className="rounded-md px-1.5 text-xs font-medium text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Ver todas
          </Link>
        </div>
      </div>

      {pendentes.length === 0 ? (
        <Card>
          <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
            <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
              <CheckCircle2 size={22} strokeWidth={1.75} className="text-text-muted" />
            </div>
            <div>
              <p className="text-sm font-medium text-text-primary">Nenhuma tarefa para hoje.</p>
              <p className="mt-1 text-[13px] text-text-muted">Tarefas com prazo de hoje aparecem aqui.</p>
            </div>
            <Button variant="outline" size="sm" onClick={abrirCriar}>
              <Plus size={15} strokeWidth={1.5} />
              Nova tarefa
            </Button>
          </div>
        </Card>
      ) : (
        <Card className="gap-0 py-0">
          {pendentes.map((t, i) => (
            <button
              key={t.id}
              type="button"
              onClick={() => abrirEditar(t)}
              style={{ animationDelay: `${Math.min(i, 8) * 30}ms`, animationFillMode: "backwards" }}
              className={cn(
                "flex items-center gap-3 px-4 py-3 text-left transition-colors animate-in fade-in-0 slide-in-from-bottom-1 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                i > 0 && "border-t border-border-subtle",
              )}
            >
              <span className={cn("size-1.5 shrink-0 rounded-full", PRIORIDADE_BAR[t.prioridade])} />
              <span className="flex-1 truncate text-sm text-text-primary">{t.titulo}</span>
              <span className="shrink-0 text-xs text-text-muted">
                {PRIORIDADE_LABEL[t.prioridade]}
                {t.atribuido && ` · ${t.atribuido.nome ?? ATOR_LABEL[t.atribuido.tipo]}`}
              </span>
            </button>
          ))}
        </Card>
      )}

      {dialogAberto && (
        <DialogTarefa
          key={tarefaEdit?.id ?? "novo"}
          onClose={() => setDialogAberto(false)}
          tarefa={tarefaEdit}
          responsaveis={responsaveis}
          onCriar={criar}
          onAtualizar={atualizar}
        />
      )}
    </section>
  )
}
