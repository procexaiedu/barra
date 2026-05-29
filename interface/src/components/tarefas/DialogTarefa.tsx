"use client"

import { useMemo, useState } from "react"
import { toast } from "sonner"
import { X } from "lucide-react"

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Combobox } from "@/components/ui/combobox"
import { cn } from "@/lib/utils"
import {
  ATOR_LABEL,
  PRIORIDADE_BAR,
  PRIORIDADE_LABEL,
  PRIORIDADE_ORDEM,
  STATUS_ACENTO,
  STATUS_LABEL,
  STATUS_ORDEM,
  atorKey,
  parseAtorKey,
} from "@/lib/tarefas"
import type {
  CriarTarefaInput,
  PatchTarefaInput,
  PrioridadeTarefa,
  ResponsavelOpcao,
  StatusTarefa,
  Tarefa,
} from "@/tipos/tarefas"

interface Props {
  /** Montado pelo pai só quando aberto (seed via inicializador, sem efeito). */
  onClose: () => void
  /** Presente = modo edição. */
  tarefa?: Tarefa | null
  responsaveis: ResponsavelOpcao[]
  onCriar: (input: CriarTarefaInput) => Promise<void>
  onAtualizar: (id: string, input: PatchTarefaInput) => Promise<void>
}

export function DialogTarefa({ onClose, tarefa, responsaveis, onCriar, onAtualizar }: Props) {
  const editando = !!tarefa

  const [titulo, setTitulo] = useState(tarefa?.titulo ?? "")
  const [descricao, setDescricao] = useState(tarefa?.descricao ?? "")
  const [prioridade, setPrioridade] = useState<PrioridadeTarefa>(tarefa?.prioridade ?? "media")
  const [status, setStatus] = useState<StatusTarefa>(tarefa?.status ?? "a_fazer")
  const [prazo, setPrazo] = useState(tarefa?.prazo ?? "")
  const [responsavel, setResponsavel] = useState(
    tarefa?.atribuido ? atorKey(tarefa.atribuido.tipo, tarefa.atribuido.id) : "",
  ) // "" = sem responsável
  const [submitting, setSubmitting] = useState(false)

  const opcoesKeys = useMemo(() => responsaveis.map((r) => atorKey(r.tipo, r.id)), [responsaveis])
  const labelPorKey = useMemo(() => {
    const m = new Map<string, string>()
    for (const r of responsaveis) m.set(atorKey(r.tipo, r.id), `${r.nome} · ${ATOR_LABEL[r.tipo]}`)
    return m
  }, [responsaveis])

  const podeSalvar = titulo.trim().length > 0 && !submitting

  const handleSubmit = async () => {
    if (!podeSalvar) return
    setSubmitting(true)
    const atribuido = responsavel ? parseAtorKey(responsavel) : null
    try {
      if (editando && tarefa) {
        const patch: PatchTarefaInput = {
          titulo: titulo.trim(),
          descricao: descricao.trim() || null,
          prioridade,
          status,
          prazo: prazo || null,
          atribuido_tipo: atribuido?.tipo ?? null,
          atribuido_id: atribuido?.id ?? null,
        }
        await onAtualizar(tarefa.id, patch)
        toast.success("Tarefa atualizada")
      } else {
        const input: CriarTarefaInput = {
          titulo: titulo.trim(),
          descricao: descricao.trim() || null,
          prioridade,
          prazo: prazo || null,
          atribuido_tipo: atribuido?.tipo ?? null,
          atribuido_id: atribuido?.id ?? null,
        }
        await onCriar(input)
        toast.success("Tarefa criada")
      }
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar tarefa")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="w-[468px] max-w-[92vw] rounded-xl border border-border bg-card p-6 shadow-2xl">
        <div className="mb-5 flex items-center justify-between">
          <DialogTitle className="font-serif text-2xl font-medium leading-none">
            {editando ? "Editar tarefa" : "Nova tarefa"}
          </DialogTitle>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-md p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary"
          >
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tarefa-titulo">Título</Label>
            <Input
              id="tarefa-titulo"
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
              placeholder="Ex.: Botar os telefones para carregar"
              maxLength={200}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="tarefa-descricao">Descrição</Label>
            <Textarea
              id="tarefa-descricao"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="Detalhes (opcional)"
              rows={3}
              maxLength={4000}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Prioridade</Label>
              <div className="flex gap-1">
                {PRIORIDADE_ORDEM.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPrioridade(p)}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium transition-all duration-150",
                      prioridade === p
                        ? "border-border-brand bg-accent text-text-primary"
                        : "border-border text-text-secondary hover:bg-surface-hover",
                    )}
                  >
                    <span className={cn("size-1.5 rounded-full", PRIORIDADE_BAR[p])} aria-hidden />
                    {PRIORIDADE_LABEL[p]}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="tarefa-prazo">Prazo</Label>
              <Input
                id="tarefa-prazo"
                type="date"
                value={prazo}
                onChange={(e) => setPrazo(e.target.value)}
              />
            </div>
          </div>

          {editando && (
            <div className="space-y-1.5">
              <Label>Status</Label>
              <div className="flex gap-1">
                {STATUS_ORDEM.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium transition-all duration-150",
                      status === s
                        ? "border-border-brand bg-accent text-text-primary"
                        : "border-border text-text-secondary hover:bg-surface-hover",
                    )}
                  >
                    <span className={cn("size-1.5 rounded-full", STATUS_ACENTO[s].bar)} aria-hidden />
                    {STATUS_LABEL[s]}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="tarefa-responsavel">Responsável</Label>
            <div className="flex items-center gap-2">
              <Combobox
                id="tarefa-responsavel"
                value={responsavel}
                onChange={setResponsavel}
                options={opcoesKeys}
                placeholder="Sem responsável"
                displayFormat={(v) => labelPorKey.get(v) ?? v}
                className="flex-1"
              />
              {responsavel && (
                <Button variant="ghost" size="sm" onClick={() => setResponsavel("")}>
                  Limpar
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!podeSalvar}>
            {editando ? "Salvar" : "Criar tarefa"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
