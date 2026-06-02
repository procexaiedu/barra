"use client"

import { useState } from "react"
import { Pencil, Trash2, CalendarClock, User2, GripVertical } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  ATOR_LABEL,
  PRIORIDADE_BAR,
  PRIORIDADE_LABEL,
  STATUS_ACENTO,
  STATUS_LABEL,
  STATUS_ORDEM,
  formatPrazoCurto,
} from "@/lib/tarefas"
import type { StatusTarefa, Tarefa } from "@/tipos/tarefas"

const HOJE = new Date().toLocaleDateString("en-CA")

interface Props {
  tarefas: Tarefa[]
  onEditar: (t: Tarefa) => void
  onExcluir: (t: Tarefa) => void
  onMoverStatus: (id: string, status: StatusTarefa) => void
}

export function BoardTarefas({ tarefas, onEditar, onExcluir, onMoverStatus }: Props) {
  const [arrastando, setArrastando] = useState<string | null>(null)
  const [sobre, setSobre] = useState<StatusTarefa | null>(null)
  const [handleAtivo, setHandleAtivo] = useState<string | null>(null)

  const porStatus = (s: StatusTarefa) => tarefas.filter((t) => t.status === s)

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {STATUS_ORDEM.map((coluna) => {
        const acento = STATUS_ACENTO[coluna]
        const itens = porStatus(coluna)
        const alvo = sobre === coluna && arrastando !== null
        return (
          <div
            key={coluna}
            onDragOver={(e) => {
              e.preventDefault()
              setSobre(coluna)
            }}
            onDragLeave={() => setSobre((c) => (c === coluna ? null : c))}
            onDrop={() => {
              if (arrastando) {
                const t = tarefas.find((x) => x.id === arrastando)
                if (t && t.status !== coluna) onMoverStatus(arrastando, coluna)
              }
              setArrastando(null)
              setSobre(null)
            }}
            className={cn(
              "flex min-h-[160px] flex-col gap-2 rounded-lg border bg-muted p-2.5 transition-all duration-150",
              alvo
                ? "border-border-brand bg-accent/40 ring-1 ring-gold-500/40"
                : "border-border",
            )}
          >
            {/* cabeçalho da coluna */}
            <div className="mb-1 flex items-center gap-2 px-1.5 pt-1">
              <span className={cn("size-1.5 rounded-full", acento.bar)} aria-hidden />
              <span className={cn("text-[11px] font-medium uppercase tracking-[0.08em]", acento.text)}>
                {STATUS_LABEL[coluna]}
              </span>
              <span className="ml-auto font-mono text-[11px] tabular-nums text-text-muted">
                {itens.length}
              </span>
            </div>

            {itens.map((t, i) => {
              const atrasada = t.prazo !== null && t.prazo < HOJE && t.status !== "feita"
              const feita = t.status === "feita"
              return (
                <article
                  key={t.id}
                  draggable={handleAtivo === t.id}
                  onDragStart={() => setArrastando(t.id)}
                  onDragEnd={() => { setArrastando(null); setHandleAtivo(null) }}
                  style={{ animationDelay: `${Math.min(i, 10) * 30}ms`, animationFillMode: "backwards" }}
                  className={cn(
                    "group relative overflow-hidden rounded-lg bg-card py-2.5 pl-7 pr-2.5 ring-1 ring-foreground/10 transition-colors duration-150 animate-in fade-in-0 slide-in-from-bottom-1",
                    "hover:bg-surface-hover",
                    arrastando === t.id && "opacity-50 ring-gold-500/50",
                  )}
                >
                  {/* acento de prioridade */}
                  <span
                    aria-hidden
                    className={cn(
                      "absolute left-0 top-0 h-full w-[3px]",
                      PRIORIDADE_BAR[t.prioridade],
                      feita && "opacity-30",
                    )}
                  />

                  {/* alça de arrastar */}
                  <span
                    onPointerDown={() => setHandleAtivo(t.id)}
                    onPointerUp={() => setHandleAtivo(null)}
                    aria-label="Arrastar tarefa"
                    className={cn(
                      "absolute left-1 top-1/2 flex -translate-y-1/2 touch-none items-center text-text-disabled",
                      "cursor-grab hover:text-text-muted active:cursor-grabbing",
                    )}
                  >
                    <GripVertical size={14} strokeWidth={1.5} aria-hidden />
                  </span>

                  <div className="flex items-start justify-between gap-2">
                    <p
                      className={cn(
                        "text-sm font-medium leading-snug",
                        feita ? "text-text-muted line-through" : "text-text-primary",
                      )}
                    >
                      {t.titulo}
                    </p>
                    <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
                      <button
                        onClick={() => onEditar(t)}
                        aria-label="Editar"
                        className="rounded-md p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Pencil size={13} strokeWidth={1.5} />
                      </button>
                      <button
                        onClick={() => onExcluir(t)}
                        aria-label="Excluir"
                        className="rounded-md p-1 text-text-muted transition-colors hover:bg-accent hover:text-danger-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <Trash2 size={13} strokeWidth={1.5} />
                      </button>
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-text-muted">
                    <span className="flex items-center gap-1">
                      <span className={cn("size-1.5 rounded-full", PRIORIDADE_BAR[t.prioridade])} />
                      {PRIORIDADE_LABEL[t.prioridade]}
                    </span>
                    {t.prazo && (
                      <span className={cn("flex items-center gap-1 font-mono tabular-nums", atrasada && "text-danger-500")}>
                        <CalendarClock size={12} strokeWidth={1.5} />
                        {formatPrazoCurto(t.prazo)}
                      </span>
                    )}
                    {t.atribuido && (
                      <span className="flex items-center gap-1 truncate">
                        <User2 size={12} strokeWidth={1.5} />
                        {t.atribuido.nome ?? `${ATOR_LABEL[t.atribuido.tipo]} (removido)`}
                      </span>
                    )}
                  </div>
                </article>
              )
            })}

            {itens.length === 0 && (
              <div className="flex flex-1 items-center justify-center rounded-md border border-dashed border-border-subtle px-2 py-6 text-center text-xs text-text-disabled">
                Arraste tarefas para cá
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
