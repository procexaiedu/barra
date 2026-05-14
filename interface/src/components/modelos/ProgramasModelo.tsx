"use client"

import { useMemo, useState } from "react"
import { Check, Loader2, Pencil, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DialogAdicionarServicoModelo } from "@/components/modelos/DialogAdicionarServicoModelo"
import { formatBRL } from "@/lib/formatters"
import type {
  Duracao,
  DuracaoInput,
  Programa,
  ProgramaInput,
  ProgramaModeloVinculo,
} from "@/tipos/modelos"

export function ProgramasModelo({
  catalogo,
  duracoes,
  vinculados,
  onVincular,
  onAtualizarPreco,
  onDesvincular,
  onCriarPrograma,
  onCriarDuracao,
}: {
  catalogo: Programa[]
  duracoes: Duracao[]
  vinculados: ProgramaModeloVinculo[]
  onVincular: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
}) {
  const [dialogOpen, setDialogOpen] = useState(false)

  const grupos = useMemo(() => agruparPorPrograma(vinculados), [vinculados])

  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <header className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-text-primary">Serviços e preços</h2>
          <p className="mt-1 text-sm text-text-muted">
            Cadastre apenas o que esta modelo realmente oferece.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setDialogOpen(true)}>
          <Plus size={13} strokeWidth={1.5} />
          Adicionar serviço
        </Button>
      </header>

      {vinculados.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted px-4 py-10 text-center">
          <p className="text-sm text-text-secondary">Nenhum serviço cadastrado ainda.</p>
          <p className="mt-1 text-xs text-text-muted">
            Use{" "}
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="text-text-primary underline-offset-2 hover:underline cursor-pointer"
            >
              Adicionar serviço
            </button>{" "}
            para definir o que ela faz e os preços de cada duração.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {grupos.map((grupo) => (
            <GrupoPrograma
              key={grupo.programaId}
              grupo={grupo}
              onAtualizarPreco={onAtualizarPreco}
              onDesvincular={onDesvincular}
            />
          ))}
        </div>
      )}

      <DialogAdicionarServicoModelo
        open={dialogOpen}
        catalogo={catalogo}
        duracoes={duracoes}
        vinculados={vinculados}
        onOpenChange={setDialogOpen}
        onCriarPrograma={onCriarPrograma}
        onCriarDuracao={onCriarDuracao}
        onVincular={onVincular}
      />
    </section>
  )
}

interface GrupoProgramaItem {
  programaId: string
  nome: string
  categoria: string | null
  linhas: ProgramaModeloVinculo[]
}

function agruparPorPrograma(vinculados: ProgramaModeloVinculo[]): GrupoProgramaItem[] {
  const map = new Map<string, GrupoProgramaItem>()
  for (const v of vinculados) {
    const existente = map.get(v.programa_id)
    if (existente) {
      existente.linhas.push(v)
    } else {
      map.set(v.programa_id, {
        programaId: v.programa_id,
        nome: v.nome,
        categoria: v.categoria,
        linhas: [v],
      })
    }
  }
  return Array.from(map.values())
}

function GrupoPrograma({
  grupo,
  onAtualizarPreco,
  onDesvincular,
}: {
  grupo: GrupoProgramaItem
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-2.5">
        <h3 className="text-sm font-semibold text-text-primary">{grupo.nome}</h3>
      </div>
      <ul className="divide-y divide-border">
        {grupo.linhas.map((linha) => (
          <LinhaServico
            key={`${linha.programa_id}:${linha.duracao_id}`}
            linha={linha}
            onAtualizarPreco={onAtualizarPreco}
            onDesvincular={onDesvincular}
          />
        ))}
      </ul>
    </div>
  )
}

function LinhaServico({
  linha,
  onAtualizarPreco,
  onDesvincular,
}: {
  linha: ProgramaModeloVinculo
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [precoInput, setPrecoInput] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const abrirEdicao = () => {
    setPrecoInput(String(linha.preco))
    setEditando(true)
  }

  const cancelar = () => {
    setEditando(false)
    setPrecoInput("")
  }

  const confirmar = async () => {
    const preco = Number(precoInput.replace(",", "."))
    if (!precoInput.trim() || isNaN(preco) || preco < 0) {
      toast.error("Informe um preço válido")
      return
    }
    setSubmitting(true)
    try {
      await onAtualizarPreco(linha.programa_id, linha.duracao_id, preco)
      toast.success("Preço atualizado")
      setEditando(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  const remover = async () => {
    setSubmitting(true)
    try {
      await onDesvincular(linha.programa_id, linha.duracao_id)
      toast.success("Serviço removido")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <li className="flex items-center justify-between gap-3 px-4 py-2.5">
      <span className="w-28 shrink-0 text-sm text-text-secondary">{linha.duracao_nome}</span>

      <div className="ml-auto flex items-center gap-2">
        {editando ? (
          <>
            <span className="text-xs text-text-muted">R$</span>
            <Input
              type="number"
              min={0}
              step={50}
              value={precoInput}
              onChange={(e) => setPrecoInput(e.target.value)}
              placeholder="Ex.: 800"
              className="h-8 w-28 bg-input text-sm tabular-nums"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmar()
                if (e.key === "Escape") cancelar()
              }}
            />
            <Button variant="primary" size="icon-sm" onClick={confirmar} disabled={submitting} aria-label="Salvar preço">
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={cancelar} disabled={submitting} aria-label="Cancelar">
              <X size={14} strokeWidth={1.5} />
            </Button>
          </>
        ) : (
          <>
            <span className="text-sm font-medium tabular-nums text-text-primary">
              {formatBRL(linha.preco)}
            </span>
            <Button variant="ghost" size="icon-sm" onClick={abrirEdicao} disabled={submitting} aria-label="Editar preço">
              <Pencil size={14} strokeWidth={1.5} />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={remover}
              disabled={submitting}
              aria-label="Remover serviço"
              className="hover:text-state-lost"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <X size={14} strokeWidth={1.5} />}
            </Button>
          </>
        )}
      </div>
    </li>
  )
}
