"use client"

import { useId, useState } from "react"
import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
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
  onCriarPrograma: (input: ProgramaInput) => Promise<Programa>
  onAtualizarPrograma: (id: string, input: Partial<ProgramaInput>) => Promise<void>
  onExcluirPrograma: (id: string) => Promise<void>
  onCriarDuracao: (input: DuracaoInput) => Promise<Duracao>
  onAtualizarDuracao: (id: string, input: Partial<DuracaoInput>) => Promise<void>
  onExcluirDuracao: (id: string) => Promise<void>
}) {
  const categoriasListId = useId()
  const categorias = [...new Set(programas.map((p) => p.categoria).filter(Boolean))] as string[]

  if (status === "loading") {
    return (
      <div aria-busy="true" className="grid gap-4 xl:grid-cols-2">
        <Skeleton className="h-80 rounded-lg" />
        <Skeleton className="h-80 rounded-lg" />
      </div>
    )
  }
  if (status === "error") {
    return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <SecaoCatalogo
        programas={programas}
        categorias={categorias}
        categoriasListId={categoriasListId}
        onCriar={onCriarPrograma}
        onAtualizar={onAtualizarPrograma}
        onExcluir={onExcluirPrograma}
      />
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
  onCriar: (input: ProgramaInput) => Promise<Programa>
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
    <section className="overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle">
      <header className="flex items-baseline justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <h2 className="flex items-center gap-2.5 text-sm font-semibold text-text-primary">
            <span className="h-3.5 w-1 rounded-full bg-gold-500" aria-hidden />
            Programas
          </h2>
          <p className="pl-[14px] text-xs text-text-muted">
            Catálogo Elite Baby. Também é possível criar serviços direto no perfil de cada modelo.
          </p>
        </div>
        <span className="font-mono tabular-nums text-xs text-text-muted">{programas.length}</span>
      </header>

      {programas.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-text-muted">
          Nenhum programa cadastrado ainda.
        </p>
      ) : (
        <div className="divide-y divide-border">
          {grupos.map(({ titulo, items }) => (
            <div key={titulo ?? "__geral__"}>
              {titulo && (
                <p className="bg-muted px-4 py-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                  {titulo}
                </p>
              )}
              <ul className="divide-y divide-border">
                {items.map((p) => (
                  <ItemPrograma
                    key={p.id}
                    programa={p}
                    listId={categoriasListId}
                    onAtualizar={onAtualizar}
                    onExcluir={onExcluir}
                  />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      <datalist id={categoriasListId}>
        {categorias.map((c) => <option key={c} value={c} />)}
      </datalist>
      <div className="flex items-center gap-2 border-t border-border bg-muted px-3 py-2.5">
        <Input
          value={form.nome}
          onChange={(e) => setForm({ ...form, nome: e.target.value })}
          placeholder="Nome do programa"
          className="h-8 flex-1 bg-input text-sm"
          onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
        />
        <Input
          list={categoriasListId}
          value={form.categoria}
          onChange={(e) => setForm({ ...form, categoria: e.target.value })}
          placeholder="Tipo (opcional)"
          className="h-8 w-36 bg-input text-sm"
        />
        <Button
          variant="primary"
          size="sm"
          onClick={salvar}
          disabled={!form.nome.trim() || submitting}
        >
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} strokeWidth={1.5} />}
          Adicionar
        </Button>
      </div>
    </section>
  )
}

function ItemPrograma({
  programa,
  listId,
  onAtualizar,
  onExcluir,
}: {
  programa: Programa
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
      <li className="flex items-center gap-2 px-3 py-2">
        <Input
          value={form.nome}
          onChange={(e) => setForm({ ...form, nome: e.target.value })}
          className="h-8 flex-1 bg-input text-sm"
          onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
          autoFocus
        />
        <Input
          list={listId}
          value={form.categoria}
          onChange={(e) => setForm({ ...form, categoria: e.target.value })}
          placeholder="Tipo"
          className="h-8 w-32 bg-input text-sm"
        />
        <Button variant="primary" size="icon-sm" onClick={salvar} disabled={!form.nome.trim() || submitting} aria-label="Salvar">
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => { setForm({ nome: programa.nome, categoria: programa.categoria ?? "" }); setEditando(false) }} disabled={submitting} aria-label="Cancelar">
          <X size={13} strokeWidth={1.5} />
        </Button>
      </li>
    )
  }

  return (
    <li className="group flex items-center justify-between gap-3 px-4 py-2 hover:bg-accent">
      <span className="text-sm text-text-primary">{programa.nome}</span>
      <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <Button variant="ghost" size="icon-sm" onClick={() => setEditando(true)} disabled={submitting} aria-label="Editar">
          <Pencil size={13} strokeWidth={1.5} />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={excluir} disabled={submitting} aria-label="Remover" className="hover:text-state-lost">
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} strokeWidth={1.5} />}
        </Button>
      </div>
    </li>
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
  onCriar: (input: DuracaoInput) => Promise<Duracao>
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
    <section className="overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle">
      <header className="flex items-baseline justify-between gap-4 border-b border-border px-4 py-3">
        <div>
          <h2 className="flex items-center gap-2.5 text-sm font-semibold text-text-primary">
            <span className="h-3.5 w-1 rounded-full bg-gold-500" aria-hidden />
            Durações
          </h2>
          <p className="pl-[14px] text-xs text-text-muted">
            Catálogo de durações. Também é possível criar durações direto no perfil.
          </p>
        </div>
        <span className="font-mono tabular-nums text-xs text-text-muted">{duracoes.length}</span>
      </header>

      {duracoes.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-text-muted">
          Nenhuma duração cadastrada ainda.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {duracoes.map((d) => (
            <ItemDuracao key={d.id} duracao={d} onAtualizar={onAtualizar} onExcluir={onExcluir} />
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2 border-t border-border bg-muted px-3 py-2.5">
        <Input
          value={form.nome}
          onChange={(e) => setForm({ nome: e.target.value })}
          placeholder="Ex.: 4 horas"
          className="h-8 flex-1 bg-input text-sm"
          onKeyDown={(e) => { if (e.key === "Enter") salvar() }}
        />
        <Button
          variant="primary"
          size="sm"
          onClick={salvar}
          disabled={!form.nome.trim() || submitting}
        >
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} strokeWidth={1.5} />}
          Adicionar
        </Button>
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
      <li className="flex items-center gap-2 px-3 py-2">
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
        <Button variant="primary" size="icon-sm" onClick={salvar} disabled={!nome.trim() || submitting} aria-label="Salvar">
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => { setNome(duracao.nome); setEditando(false) }} disabled={submitting} aria-label="Cancelar">
          <X size={13} strokeWidth={1.5} />
        </Button>
      </li>
    )
  }

  return (
    <li className="group flex items-center justify-between gap-3 px-4 py-2 hover:bg-accent">
      <span className="text-sm text-text-primary">{duracao.nome}</span>
      <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <Button variant="ghost" size="icon-sm" onClick={() => setEditando(true)} disabled={submitting} aria-label="Editar">
          <Pencil size={13} strokeWidth={1.5} />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={excluir} disabled={submitting} aria-label="Remover" className="hover:text-state-lost">
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} strokeWidth={1.5} />}
        </Button>
      </div>
    </li>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
