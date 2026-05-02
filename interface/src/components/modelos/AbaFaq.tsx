"use client"

import { useMemo, useState } from "react"
import { FileQuestion, Pencil, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { EscopoFaq, FaqItem } from "@/tipos/modelos"

export function AbaFaq({
  faq,
  onAdicionar,
  onEditar,
  onExcluir,
}: {
  faq: FaqItem[]
  onAdicionar: () => void
  onEditar: (faq: FaqItem) => void
  onExcluir: (faq: FaqItem) => void
}) {
  const [busca, setBusca] = useState("")
  const [escopo, setEscopo] = useState<EscopoFaq>("especificas")
  const items = useMemo(() => {
    const termo = busca.trim().toLowerCase()
    return faq.filter((item) => {
      if (escopo === "especificas" && item.modelo_id === null) return false
      if (escopo === "globais" && item.modelo_id !== null) return false
      if (!termo) return true
      return [item.pergunta, item.resposta, item.tags.join(" ")].some((valor) => valor.toLowerCase().includes(termo))
    })
  }, [busca, escopo, faq])

  return (
    <div className="space-y-5">
      <section aria-label="Filtros de duvidas" className="flex flex-wrap items-end gap-3">
        <div className="min-w-80 flex-1">
          <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar pergunta, resposta ou tag" className="h-10 bg-input" />
        </div>
        <label className="grid gap-1 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          Tipo
          <select value={escopo} onChange={(e) => setEscopo(e.target.value as EscopoFaq)} className="h-10 rounded-lg border border-input bg-input px-3 text-sm normal-case tracking-normal text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
            <option value="especificas">Desta modelo</option>
            <option value="globais">Gerais</option>
            <option value="todas">Todas</option>
          </select>
        </label>
        <Button variant="primary" onClick={onAdicionar}>Adicionar resposta</Button>
      </section>
      {items.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <div className="flex gap-3">
            <FileQuestion className="mt-0.5 text-text-muted" size={20} strokeWidth={1.5} />
            <div>
              <p className="text-sm text-text-primary">Nenhuma resposta cadastrada para esta modelo.</p>
              <p className="mt-1 text-[13px] text-text-muted">Adicione orientacoes para perguntas frequentes dos clientes.</p>
            </div>
          </div>
        </div>
      ) : (
        <section aria-label="Lista de respostas" className="space-y-3">
          {items.map((item) => {
            const global = item.modelo_id === null
            const bloqueada = global && escopo !== "globais"
            return (
              <article key={item.id} className="rounded-lg border border-border bg-card p-4">
                <div className="mb-2 flex flex-wrap gap-2">
                  {global && <span className="rounded-full bg-ink-300 px-2 py-1 text-xs text-text-muted">geral</span>}
                  {item.tags.map((tag) => <span key={tag} className="rounded-full bg-ink-300 px-2 py-1 text-xs text-text-muted">{tag}</span>)}
                </div>
                <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-primary">{item.pergunta}</h3>
                <p className="mt-2 line-clamp-2 text-sm text-text-muted">{item.resposta}</p>
                <div className="mt-3 flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => onEditar(item)} disabled={bloqueada}>
                    <Pencil size={14} strokeWidth={1.5} />
                    Editar
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => onExcluir(item)} disabled={bloqueada}>
                    <Trash2 size={14} strokeWidth={1.5} />
                    Remover
                  </Button>
                </div>
              </article>
            )
          })}
        </section>
      )}
    </div>
  )
}
