"use client"

import { Pencil, Trash2, CalendarClock, User2, Check } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  ATOR_LABEL,
  PRIORIDADE_BAR,
  PRIORIDADE_LABEL,
  STATUS_ACENTO,
  STATUS_LABEL,
  formatPrazoCurto,
} from "@/lib/tarefas"
import type { Tarefa } from "@/tipos/tarefas"

const HOJE = new Date().toLocaleDateString("en-CA")

interface Props {
  tarefas: Tarefa[]
  onEditar: (t: Tarefa) => void
  onExcluir: (t: Tarefa) => void
  onConcluir: (t: Tarefa) => void
}

export function ListaTarefas({ tarefas, onEditar, onExcluir, onConcluir }: Props) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface-raised">
      {tarefas.map((t, i) => {
        const feita = t.status === "feita"
        const atrasada = t.prazo !== null && t.prazo < HOJE && !feita
        return (
          <div
            key={t.id}
            style={{ animationDelay: `${Math.min(i, 12) * 28}ms`, animationFillMode: "backwards" }}
            className={cn(
              "group relative flex items-center gap-3.5 py-3 pl-5 pr-3 transition-colors duration-150 animate-in fade-in-0 slide-in-from-bottom-1",
              "hover:bg-surface-hover",
              i > 0 && "border-t border-border-subtle",
            )}
          >
            {/* acento de prioridade — barra vertical fina à esquerda */}
            <span
              aria-hidden
              className={cn(
                "absolute left-0 top-0 h-full w-[3px] transition-opacity",
                PRIORIDADE_BAR[t.prioridade],
                feita ? "opacity-30" : "opacity-90",
              )}
            />

            <button
              onClick={() => onConcluir(t)}
              aria-label={feita ? "Reabrir tarefa" : "Concluir tarefa"}
              className={cn(
                "flex size-[19px] shrink-0 items-center justify-center rounded-full border transition-all duration-150",
                feita
                  ? "border-success-500 bg-success-500 text-white"
                  : "border-border-strong text-transparent hover:border-gold-500 hover:text-gold-500/40",
              )}
            >
              <Check size={11} strokeWidth={3} />
            </button>

            <button onClick={() => onEditar(t)} className="flex min-w-0 flex-1 flex-col items-start gap-1 text-left">
              <span
                className={cn(
                  "max-w-full truncate text-sm font-medium",
                  feita ? "text-text-muted line-through" : "text-text-primary",
                )}
              >
                {t.titulo}
              </span>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
                <span className={cn("font-mono uppercase tracking-[0.08em]", STATUS_ACENTO[t.status].text)}>
                  {STATUS_LABEL[t.status]}
                </span>
                <span className="text-border-strong">·</span>
                <span>{PRIORIDADE_LABEL[t.prioridade]}</span>
                {t.prazo && (
                  <>
                    <span className="text-border-strong">·</span>
                    <span className={cn("flex items-center gap-1 font-mono", atrasada && "text-danger-500")}>
                      <CalendarClock size={12} strokeWidth={1.5} />
                      {formatPrazoCurto(t.prazo)}
                    </span>
                  </>
                )}
                {t.atribuido && (
                  <>
                    <span className="text-border-strong">·</span>
                    <span className="flex items-center gap-1">
                      <User2 size={12} strokeWidth={1.5} />
                      {t.atribuido.nome ?? `${ATOR_LABEL[t.atribuido.tipo]} (removido)`}
                    </span>
                  </>
                )}
              </span>
            </button>

            <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
              <button
                onClick={() => onEditar(t)}
                aria-label="Editar"
                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-pressed hover:text-text-primary"
              >
                <Pencil size={14} strokeWidth={1.5} />
              </button>
              <button
                onClick={() => onExcluir(t)}
                aria-label="Excluir"
                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-pressed hover:text-danger-500"
              >
                <Trash2 size={14} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
