"use client"

import { useId, useState } from "react"
import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { BannerErro } from "@/components/layout/BannerErro"
import type { Duracao, DuracaoInput, Programa, ProgramaInput } from "@/tipos/modelos"

export function PainelProgramas({
  programas,
  duracoes,
  status,
  error,
  onRetry,
  onCriarPrograma,
  onAtualizarPrograma,
  onExcluirPrograma,
  onCriarDuracao,
  onAtualizarDuracao,
  onExcluirDuracao,
}: {
  programas: Programa[]
  duracoes: Duracao[]
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onCriarPrograma: (input: ProgramaInput) => Promise<void>
  onAtualizarPrograma: (id: string, input: Partial<ProgramaInput>) => Promise<void>
  onExcluirPrograma: (id: string) => Promise<void>
  onCriarDuracao: (input: DuracaoInput) => Promise<void>
  onAtualizarDuracao: (id: string, input: Partial<DuracaoInput>) => Promise<void>
  onExcluirDuracao: (id: string) => Promise<void>
}) {
  const categoriasListId = useId()
  const categorias = [...new Set(programas.map((p) => p.categoria).filter(Boolean))] as string[]

  if (status === "loading") {
    return <p className="text-sm text-text-muted">Carregando programas...</p>
  }
  if (status === "error") {
    return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  }

  return (
    <div className="space-y-6">
      {/* Programas */}
      <SecaoCatalogo
        programas={programas}
        categorias={categorias}
        categoriasListId={categoriasListId}
        onCriar={onCriarPrograma}
        onAtualizar={onAtualizarPrograma}
        onExcluir={onExcluirPrograma}
      />

      {/* Durações */}
      <SecaoDuracoes
        duracoes={duracoes}
        onCriar={onCriarDuracao}
        onAtualizar={onAtualizarDuracao}
        onExcluir={onExcluirDuracao}
      />
    </div>
  )
}

// ── Seção Programas ───────────────────────────────────────────────────────────

function SecaoCatalogo({
  programas,
  categorias,
  categoriasListId,
  onCriar,
  onAtualizar,
  onExcluir,
}: {
  programas: Programa[]
  categorias: string[]
  categoriasListId: string
  onCriar: (input: ProgramaInput) => Promise<void>
  onAtualizar: (id: string, input: Partial<ProgramaInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [form, setForm] = useState({ nome: "", categoria: "" })
  const [submitting, setSubmitting] = useState(false)

  const salvar = async () => {
    if (!form.nome.trim()) return
    setSubmitting(true)
    try {
      await onCriar({ nome: form.nome.trim(), categoria: form.categoria.trim() || null })
      toast.success("Programa adicionado")
      setForm({ nome: "", categoria: "" })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao adicionar programa")
    } finally {
      setSubmitting(false)
    }
  }

  const grupos = agrupar(programas)

  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-base font-semibold text-text-primary">Programas</h2>
      <p className="mb-5 text-sm text-text-muted">
        Serviços oferecidos pela agência. Os preços são definidos por modelo.
      </p>

      {programas.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-text-muted mb-4">
          Nenhum programa cadastrado.
        </p>
      ) : (
        <div className="space-y-4 mb-4">
          {grupos.map(({ titulo, items }) => (
            <div key={titulo ?? "__geral__"}>
              {titulo && (
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
                  {titulo}
                </p>
              )}
              <div className="space-y-1.5">
                {items.map((p) => (
                  <ItemPrograma
                    key={p.id}
                    programa={p}
                    categorias={categorias}
                    listId={categoriasListId}
                    onAtualizar={onAtualizar}
                    onExcluir={onExcluir}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <datalist id={categoriasListId}>
        {categorias.map((c) => <option key={c} value={c} />)}
      </datalist>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] border-t border-border pt-4">
        <Campo label="Nome">
          <Input
            value={form.nome}
            onChange={(e) => setForm({ ...form, nome: e.target.value })}
            placeholder="Ex.: Casal"
            className="h-9 bg-input"
            onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
          />
        </Campo>
        <Campo label="Tipo (opcional)">
          <Input
            list={categoriasListId}
            value={form.categoria}
            onChange={(e) => setForm({ ...form, categoria: e.target.value })}
            placeholder="Ex.: Especial"
            className="h-9 bg-input"
          />
        </Campo>
        <div className="flex items-end">
          <Button
            variant="primary"
            onClick={salvar}
            disabled={!form.nome.trim() || submitting}
            className="h-9 w-full sm:w-auto"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} strokeWidth={1.5} />}
            Adicionar
          </Button>
        </div>
      </div>
    </section>
  )
}

function ItemPrograma({
  programa,
  categorias,
  listId,
  onAtualizar,
  onExcluir,
}: {
  programa: Programa
  categorias: string[]
  listId: string
  onAtualizar: (id: string, input: Partial<ProgramaInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [form, setForm] = useState({ nome: programa.nome, categoria: programa.categoria ?? "" })
  const [submitting, setSubmitting] = useState(false)

  const salvar = async () => {
    if (!form.nome.trim()) return
    setSubmitting(true)
    try {
      await onAtualizar(programa.id, { nome: form.nome.trim(), categoria: form.categoria.trim() || null })
      toast.success("Programa atualizado")
      setEditando(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  const excluir = async () => {
    setSubmitting(true)
    try {
      await onExcluir(programa.id)
      toast.success("Programa removido")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
      setSubmitting(false)
    }
  }

  if (editando) {
    return (
      <article className="rounded-lg border border-border bg-ink-100 px-3 py-2.5">
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <Campo label="Nome">
            <Input
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
              className="h-8 bg-input text-sm"
              onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
            />
          </Campo>
          <Campo label="Tipo">
            <Input
              list={listId}
              value={form.categoria}
              onChange={(e) => setForm({ ...form, categoria: e.target.value })}
              className="h-8 bg-input text-sm"
            />
          </Campo>
          <div className="flex items-end gap-1.5">
            <Button variant="primary" size="sm" onClick={salvar} disabled={!form.nome.trim() || submitting}>
              {submitting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => { setForm({ nome: programa.nome, categoria: programa.categoria ?? "" }); setEditando(false) }} disabled={submitting}>
              <X size={13} strokeWidth={1.5} />
            </Button>
          </div>
        </div>
      </article>
    )
  }

  return (
    <article className="flex items-center justify-between gap-3 rounded-lg border border-border bg-ink-100 px-3 py-2.5">
      <span className="text-sm font-medium text-text-primary">{programa.nome}</span>
      <div className="flex gap-1">
        <Button variant="ghost" size="sm" onClick={() => setEditando(true)} disabled={submitting}>
          <Pencil size={13} strokeWidth={1.5} />
        </Button>
        <Button variant="ghost" size="sm" onClick={excluir} disabled={submitting}>
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} strokeWidth={1.5} />}
        </Button>
      </div>
    </article>
  )
}

// ── Seção Durações ────────────────────────────────────────────────────────────

function SecaoDuracoes({
  duracoes,
  onCriar,
  onAtualizar,
  onExcluir,
}: {
  duracoes: Duracao[]
  onCriar: (input: DuracaoInput) => Promise<void>
  onAtualizar: (id: string, input: Partial<DuracaoInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [form, setForm] = useState({ nome: "" })
  const [submitting, setSubmitting] = useState(false)

  const salvar = async () => {
    if (!form.nome.trim()) return
    setSubmitting(true)
    try {
      await onCriar({ nome: form.nome.trim(), ordem: duracoes.length })
      toast.success("Duração adicionada")
      setForm({ nome: "" })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao adicionar duração")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-base font-semibold text-text-primary">Durações</h2>
      <p className="mb-5 text-sm text-text-muted">
        Opções de duração disponíveis para todos os programas.
      </p>

      {duracoes.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-text-muted mb-4">
          Nenhuma duração cadastrada.
        </p>
      ) : (
        <div className="space-y-1.5 mb-4">
          {duracoes.map((d) => (
            <ItemDuracao key={d.id} duracao={d} onAtualizar={onAtualizar} onExcluir={onExcluir} />
          ))}
        </div>
      )}

      <div className="flex gap-3 border-t border-border pt-4">
        <Campo label="Nome" className="flex-1">
          <Input
            value={form.nome}
            onChange={(e) => setForm({ nome: e.target.value })}
            placeholder="Ex.: 4 horas"
            className="h-9 bg-input"
            onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
          />
        </Campo>
        <div className="flex items-end">
          <Button
            variant="primary"
            onClick={salvar}
            disabled={!form.nome.trim() || submitting}
            className="h-9"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} strokeWidth={1.5} />}
            Adicionar
          </Button>
        </div>
      </div>
    </section>
  )
}

function ItemDuracao({
  duracao,
  onAtualizar,
  onExcluir,
}: {
  duracao: Duracao
  onAtualizar: (id: string, input: Partial<DuracaoInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [nome, setNome] = useState(duracao.nome)
  const [submitting, setSubmitting] = useState(false)

  const salvar = async () => {
    if (!nome.trim()) return
    setSubmitting(true)
    try {
      await onAtualizar(duracao.id, { nome: nome.trim() })
      toast.success("Duração atualizada")
      setEditando(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  const excluir = async () => {
    setSubmitting(true)
    try {
      await onExcluir(duracao.id)
      toast.success("Duração removida")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
      setSubmitting(false)
    }
  }

  if (editando) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-ink-100 px-3 py-2">
        <Input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          className="h-8 flex-1 bg-input text-sm"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter") salvar()
            if (e.key === "Escape") { setNome(duracao.nome); setEditando(false) }
          }}
        />
        <Button variant="primary" size="sm" onClick={salvar} disabled={!nome.trim() || submitting}>
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => { setNome(duracao.nome); setEditando(false) }} disabled={submitting}>
          <X size={13} strokeWidth={1.5} />
        </Button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-ink-100 px-3 py-2.5">
      <span className="text-sm text-text-primary">{duracao.nome}</span>
      <div className="flex gap-1">
        <Button variant="ghost" size="sm" onClick={() => setEditando(true)} disabled={submitting}>
          <Pencil size={13} strokeWidth={1.5} />
        </Button>
        <Button variant="ghost" size="sm" onClick={excluir} disabled={submitting}>
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} strokeWidth={1.5} />}
        </Button>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Campo({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={`grid gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted ${className ?? ""}`}>
      {label}
      {children}
    </label>
  )
}

function agrupar(programas: Programa[]): { titulo: string | null; items: Programa[] }[] {
  const geral: Programa[] = []
  const porCategoria = new Map<string, Programa[]>()

  for (const p of programas) {
    if (!p.categoria) {
      geral.push(p)
    } else {
      const lista = porCategoria.get(p.categoria) ?? []
      lista.push(p)
      porCategoria.set(p.categoria, lista)
    }
  }

  const grupos: { titulo: string | null; items: Programa[] }[] = []
  if (geral.length > 0) grupos.push({ titulo: null, items: geral })
  for (const [titulo, items] of porCategoria) {
    grupos.push({ titulo, items })
  }
  return grupos
}
