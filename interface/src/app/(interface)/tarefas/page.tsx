"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Plus, LayoutList, LayoutGrid, ListChecks, UserCheck } from "lucide-react"

import { useTarefas, type FiltrosTarefas } from "@/hooks/useTarefas"
import { DialogTarefa } from "@/components/tarefas/DialogTarefa"
import { ListaTarefas } from "@/components/tarefas/ListaTarefas"
import { BoardTarefas } from "@/components/tarefas/BoardTarefas"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { PageHeader } from "@/components/layout/PageHeader"
import { BuscaFiltro } from "@/components/filtros/BuscaFiltro"
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

const FILTRO_PRIORIDADE: { valor: FiltrosTarefas["prioridade"]; label: string }[] = [
  { valor: "todas", label: "Toda prioridade" },
  { valor: "alta", label: "Alta" },
  { valor: "media", label: "Média" },
  { valor: "baixa", label: "Baixa" },
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
    <div className="flex rounded-lg border border-border bg-muted p-0.5">
      {opcoes.map((o) => (
        <button
          key={o.valor}
          onClick={() => onChange(o.valor)}
          aria-pressed={valor === o.valor}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-all duration-150",
            "aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm",
            "text-text-muted hover:text-text-primary",
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
    busca: "",
    status: "todos",
    prioridade: "todas",
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
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Tarefas"
        description="Gestão interna da operação — sem cliente, IA ou agenda."
        action={{
          label: "Nova tarefa",
          onClick: abrirCriar,
          icon: <Plus size={16} strokeWidth={1.5} />,
        }}
      >
        <div className="flex rounded-lg border border-border bg-muted p-0.5">
          {(["lista", "board"] as const).map((v) => {
            const Icon = v === "lista" ? LayoutList : LayoutGrid
            return (
              <button
                key={v}
                onClick={() => setVisao(v)}
                aria-label={v === "lista" ? "Visão em lista" : "Visão em board"}
                aria-pressed={visao === v}
                className={cn(
                  "rounded-md p-1.5 transition-all duration-150",
                  "aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm",
                  "text-text-muted hover:text-text-primary",
                )}
              >
                <Icon size={16} strokeWidth={1.5} />
              </button>
            )
          })}
        </div>
      </PageHeader>

      <section aria-label="Tarefas" className="flex flex-col gap-3">
        {/* Filtros */}
        <div className="flex flex-col gap-2">
          <BuscaFiltro
            value={filtros.busca}
            onChange={(busca) => setFiltros((f) => ({ ...f, busca }))}
            placeholder="Buscar tarefa"
            className="max-w-md"
          />
          <div className="flex flex-wrap items-center gap-2">
          <Segmento
            opcoes={FILTRO_STATUS}
            valor={filtros.status}
            onChange={(v) => setFiltros((f) => ({ ...f, status: v }))}
          />
          <Segmento
            opcoes={FILTRO_PRIORIDADE}
            valor={filtros.prioridade}
            onChange={(v) => setFiltros((f) => ({ ...f, prioridade: v }))}
          />
          <Segmento
            opcoes={FILTRO_PRAZO}
            valor={filtros.prazo}
            onChange={(v) => setFiltros((f) => ({ ...f, prazo: v }))}
          />
          <button
            onClick={() => setFiltros((f) => ({ ...f, minhas: !f.minhas }))}
            aria-pressed={filtros.minhas}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all duration-150",
              filtros.minhas
                ? "border-border-brand bg-accent text-text-brand"
                : "border-border text-text-muted hover:text-text-primary",
            )}
          >
            <UserCheck size={13} strokeWidth={1.5} />
            Minhas
          </button>

          {status === "success" && (
            <span className="ml-auto text-xs font-medium tabular-nums text-text-muted">
              {total} {total === 1 ? "tarefa" : "tarefas"}
            </span>
          )}
          </div>
        </div>

        {status === "loading" && (
          <div aria-busy="true" className="flex flex-col gap-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[58px] rounded-lg" />
            ))}
          </div>
        )}

        {status === "error" && (
          <BannerErro mensagem={error ?? undefined} onRetry={() => void recarregar()} />
        )}

        {status === "success" && total === 0 && (
          <Card>
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
                <ListChecks size={22} strokeWidth={1.75} className="text-text-muted" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">Nada na lista.</p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Crie a primeira tarefa da operação para começar.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={abrirCriar}>
                <Plus size={15} strokeWidth={1.5} />
                Nova tarefa
              </Button>
            </div>
          </Card>
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
      </section>

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
