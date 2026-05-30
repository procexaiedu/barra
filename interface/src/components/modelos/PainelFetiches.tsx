"use client"

import { useState } from "react"
import { Check, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { BannerErro } from "@/components/layout/BannerErro"
import { FeticheValor } from "@/components/comum/FeticheValor"
import type { Fetiche, FeticheInput } from "@/tipos/modelos"

export function PainelFetiches({
  fetiches,
  status,
  error,
  onRetry,
  onCriar,
  onAtualizar,
  onExcluir,
}: {
  fetiches: Fetiche[]
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onCriar: (input: FeticheInput) => Promise<Fetiche>
  onAtualizar: (id: string, input: Partial<FeticheInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [form, setForm] = useState({ nome: "" })
  const [submitting, setSubmitting] = useState(false)

  if (status === "loading") {
    return <p className="text-sm text-text-muted">Carregando fetiches...</p>
  }
  if (status === "error") {
    return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  }

  const salvar = async () => {
    if (!form.nome.trim()) return
    setSubmitting(true)
    try {
      await onCriar({ nome: form.nome.trim(), ordem: fetiches.length })
      toast.success("Fetiche adicionado")
      setForm({ nome: "" })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao adicionar fetiche")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="overflow-hidden rounded-lg border border-border bg-card">
        <header className="flex items-baseline justify-between gap-4 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Fetiches</h2>
            <p className="text-xs text-text-muted">
              Todos os fetiches da agência. Cada modelo escolhe os dela no perfil.
            </p>
          </div>
          <span className="text-xs text-text-muted">{fetiches.length}</span>
        </header>

        {fetiches.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-text-muted">
            Nenhum fetiche cadastrado.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {fetiches.map((f) => (
              <ItemFetiche key={f.id} fetiche={f} onAtualizar={onAtualizar} onExcluir={onExcluir} />
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2 border-t border-border bg-muted px-3 py-2.5">
          <Input
            value={form.nome}
            onChange={(e) => setForm({ nome: e.target.value })}
            placeholder="Nome do fetiche"
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

      <aside className="h-fit rounded-lg border border-border bg-card p-5">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          Como funciona
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          No perfil de cada modelo você marca quais ela faz e quanto cobra:
        </p>
        <dl className="mt-4 space-y-3">
          <div className="flex items-start gap-3">
            <dt className="pt-0.5"><FeticheValor preco={null} /></dt>
            <dd className="text-sm leading-relaxed text-text-secondary">
              Sem preço: <span className="text-text-primary">já incluso</span> no valor do programa.
            </dd>
          </div>
          <div className="flex items-start gap-3">
            <dt className="pt-0.5"><FeticheValor preco={200} /></dt>
            <dd className="text-sm leading-relaxed text-text-secondary">
              Com preço: a IA <span className="text-text-primary">cota como adicional</span> por cima do programa.
            </dd>
          </div>
        </dl>
        <p className="mt-4 border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
          Na conversa, a IA só oferece o que está marcado e recusa o resto com naturalidade.
        </p>
      </aside>
    </div>
  )
}

function ItemFetiche({
  fetiche,
  onAtualizar,
  onExcluir,
}: {
  fetiche: Fetiche
  onAtualizar: (id: string, input: Partial<FeticheInput>) => Promise<void>
  onExcluir: (id: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [nome, setNome] = useState(fetiche.nome)
  const [submitting, setSubmitting] = useState(false)

  const salvar = async () => {
    if (!nome.trim()) return
    setSubmitting(true)
    try {
      await onAtualizar(fetiche.id, { nome: nome.trim() })
      toast.success("Fetiche atualizado")
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
      await onExcluir(fetiche.id)
      toast.success("Fetiche removido")
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
            if (e.key === "Escape") { setNome(fetiche.nome); setEditando(false) }
          }}
        />
        <Button variant="primary" size="icon-sm" onClick={salvar} disabled={!nome.trim() || submitting} aria-label="Salvar">
          {submitting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2} />}
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => { setNome(fetiche.nome); setEditando(false) }} disabled={submitting} aria-label="Cancelar">
          <X size={13} strokeWidth={1.5} />
        </Button>
      </li>
    )
  }

  return (
    <li className="group flex items-center justify-between gap-3 px-4 py-2 hover:bg-accent">
      <span className="text-sm text-text-primary">{fetiche.nome}</span>
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
