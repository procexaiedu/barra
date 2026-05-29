"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Plus, LayoutList, LayoutGrid, ListChecks, UserCheck } from "lucide-react"

import { useTarefas, type FiltrosTarefas } from "@/hooks/useTarefas"
import { DialogTarefa } from "@/components/tarefas/DialogTarefa"
import { ListaTarefas } from "@/components/tarefas/ListaTarefas"
import { BoardTarefas } from "@/components/tarefas/BoardTarefas"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { STATUS_LABEL } from "@/lib/tarefas"
import type { StatusTarefa, Tarefa } from "@/tipos/tarefas"

type Visao = "lista" | "board"

const FILTRO_STATUS: { valor: FiltrosTarefas["status"]; label: string }[] = [
  { valor: "todos", label: "Todas" },
  { valor: "a_fazer", label: STATUS_LABEL.a_fazer },
  { valor: "fazendo", label: STATUS_LABEL.fazendo },
  { valor: "feita", label: STATUS_LABEL.feita },
]

const FILTRO_PRAZO: { valor: FiltrosTarefas["prazo"]; label: string }[] = [
  { valor: "todos", label: "Qualquer prazo" },
  { valor: "hoje", label: "Hoje" },
  { valor: "semana", label: "Semana" },
  { valor: "atrasadas", label: "Atrasadas" },
]

function Segmento<T extends string>({
  opcoes,
  valor,
  onChange,
}: {
  opcoes: { valor: T; label: string }[]
  valor: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex rounded-lg border border-border bg-surface-raised p-0.5">
      {opcoes.map((o) => (
        <button
          key={o.valor}
          onClick={() => onChange(o.valor)}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-150",
            valor === o.valor
              ? "bg-accent text-text-brand shadow-sm"
              : "text-text-secondary hover:text-text-primary",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export default function TarefasPage() {
  const [filtros, setFiltros] = useState<FiltrosTarefas>({
    status: "todos",
    prazo: "todos",
    minhas: false,
  })
  const [visao, setVisao] = useState<Visao>("lista")
  const [dialogAberto, setDialogAberto] = useState(false)
  const [tarefaEdit, setTarefaEdit] = useState<Tarefa | null>(null)
  const [tarefaExcluir, setTarefaExcluir] = useState<Tarefa | null>(null)

  const { tarefas, status, error, responsaveis, recarregar, criar, atualizar, excluir } =
    useTarefas(filtros)

  const abrirCriar = () => {
    setTarefaEdit(null)
    setDialogAberto(true)
  }
  const abrirEditar = (t: Tarefa) => {
    setTarefaEdit(t)
    setDialogAberto(true)
  }

  const moverStatus = async (id: string, novo: StatusTarefa) => {
    try {
      await atualizar(id, { status: novo })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao mover tarefa")
    }
  }

  const concluir = async (t: Tarefa) => {
    await moverStatus(t.id, t.status === "feita" ? "a_fazer" : "feita")
  }

  const confirmarExclusao = async () => {
    if (!tarefaExcluir) return
    try {
      await excluir(tarefaExcluir.id)
      toast.success("Tarefa excluída")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao excluir tarefa")
    } finally {
      setTarefaExcluir(null)
    }
  }

  const total = tarefas.length

  return (
    <div className="mx-auto max-w-[1180px] px-8 py-9">
      {/* Cabeçalho editorial */}
      <header className="mb-7">
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.28em] text-text-muted">
          Operação
        </p>
        <div className="mt-1.5 flex items-end justify-between gap-4">
          <h1 className="font-serif text-[40px] font-medium leading-[0.9] text-text-primary">
            Tarefas
          </h1>
          <Button variant="primary" onClick={abrirCriar}>
            <Plus size={16} strokeWidth={1.5} />
            Nova tarefa
          </Button>
        </div>
        <div className="mt-3.5 flex items-center gap-3">
          <span className="h-px flex-1 bg-gradient-to-r from-gold-500/55 to-transparent" />
          {status === "success" && (
            <span className="font-mono text-[11px] tracking-wider text-text-muted">
              {total} {total === 1 ? "tarefa" : "tarefas"}
            </span>
          )}
        </div>
      </header>

      {/* Filtros */}
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <Segmento
          opcoes={FILTRO_STATUS}
          valor={filtros.status}
          onChange={(v) => setFiltros((f) => ({ ...f, status: v }))}
        />
        <Segmento
          opcoes={FILTRO_PRAZO}
          valor={filtros.prazo}
          onChange={(v) => setFiltros((f) => ({ ...f, prazo: v }))}
        />
        <button
          onClick={() => setFiltros((f) => ({ ...f, minhas: !f.minhas }))}
          className={cn(
            "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all duration-150",
            filtros.minhas
              ? "border-border-brand bg-accent text-text-brand"
              : "border-border text-text-secondary hover:bg-surface-hover",
          )}
        >
          <UserCheck size={13} strokeWidth={1.5} />
          Minhas
        </button>

        <div className="ml-auto flex rounded-lg border border-border bg-surface-raised p-0.5">
          {(["lista", "board"] as const).map((v) => {
            const Icon = v === "lista" ? LayoutList : LayoutGrid
            return (
              <button
                key={v}
                onClick={() => setVisao(v)}
                aria-label={v === "lista" ? "Visão em lista" : "Visão em board"}
                className={cn(
                  "rounded-md p-1.5 transition-colors",
                  visao === v
                    ? "bg-accent text-text-brand"
                    : "text-text-muted hover:text-text-primary",
                )}
              >
                <Icon size={16} strokeWidth={1.5} />
              </button>
            )
          })}
        </div>
      </div>

      {status === "loading" && (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[58px] rounded-xl" />
          ))}
        </div>
      )}

      {status === "error" && (
        <div className="rounded-xl border border-danger-500/30 bg-danger-500/5 px-6 py-8 text-center">
          <p className="text-sm text-danger-500">{error ?? "Erro ao carregar tarefas."}</p>
          <div className="mt-4">
            <Button variant="outline" size="sm" onClick={() => void recarregar()}>
              Tentar de novo
            </Button>
          </div>
        </div>
      )}

      {status === "success" && total === 0 && (
        <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border-strong bg-surface-raised/60 px-6 py-16 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-surface-hover ring-1 ring-border-subtle">
            <ListChecks size={22} strokeWidth={1.5} className="text-gold-500" />
          </div>
          <div>
            <p className="font-serif text-xl font-medium text-text-primary">Nada na lista</p>
            <p className="mt-1 text-[13px] text-text-muted">
              Crie a primeira tarefa da operação para começar.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={abrirCriar}>
            <Plus size={15} strokeWidth={1.5} />
            Nova tarefa
          </Button>
        </div>
      )}

      {status === "success" && total > 0 && (
        visao === "lista" ? (
          <ListaTarefas
            tarefas={tarefas}
            onEditar={abrirEditar}
            onExcluir={setTarefaExcluir}
            onConcluir={concluir}
          />
        ) : (
          <BoardTarefas
            tarefas={tarefas}
            onEditar={abrirEditar}
            onExcluir={setTarefaExcluir}
            onMoverStatus={moverStatus}
          />
        )
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

      <AlertDialog open={tarefaExcluir !== null} onOpenChange={(o) => { if (!o) setTarefaExcluir(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Excluir tarefa?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{tarefaExcluir?.titulo}&rdquo; será removida permanentemente. Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={confirmarExclusao}>
              Excluir
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
