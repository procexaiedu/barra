"use client"

import { useMemo, useState } from "react"
import { FileQuestion, Pencil, Search, Trash2 } from "lucide-react"
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
    <div className="space-y-3">
      <section aria-label="Filtros de duvidas" className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-72 flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" size={14} strokeWidth={1.5} />
          <Input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar pergunta, resposta ou tag" className="h-9 bg-input pl-9" />
        </div>
        <select aria-label="Tipo" value={escopo} onChange={(e) => setEscopo(e.target.value as EscopoFaq)} className="h-9 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          <option value="especificas">Desta modelo</option>
          <option value="globais">Gerais</option>
          <option value="todas">Todas</option>
        </select>
        <Button variant="primary" size="sm" onClick={onAdicionar}>Adicionar resposta</Button>
      </section>
      {items.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <div className="flex gap-3">
            <FileQuestion className="mt-0.5 text-text-muted" size={18} strokeWidth={1.5} />
            <div>
              <p className="text-sm text-text-primary">Nenhuma resposta cadastrada para esta modelo.</p>
              <p className="mt-1 text-xs text-text-muted">Adicione orientações para perguntas frequentes dos clientes.</p>
            </div>
          </div>
        </div>
      ) : (
        <section aria-label="Lista de respostas" className="overflow-hidden rounded-lg border border-border bg-card">
          <ul className="divide-y divide-border">
            {items.map((item) => {
              const global = item.modelo_id === null
              const bloqueada = global && escopo !== "globais"
              return (
                <li key={item.id} className="group px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="truncate text-sm font-semibold text-text-primary">{item.pergunta}</h3>
                        {global && <span className="shrink-0 rounded-full bg-ink-300 px-2 py-0.5 text-[10px] uppercase tracking-wider text-text-muted">geral</span>}
                      </div>
                      <p className="mt-1 line-clamp-2 text-sm text-text-secondary">{item.resposta}</p>
                      {item.tags.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {item.tags.map((tag) => <span key={tag} className="rounded bg-ink-200 px-1.5 py-0.5 text-[11px] text-text-muted">{tag}</span>)}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <Button variant="ghost" size="icon-sm" onClick={() => onEditar(item)} disabled={bloqueada} aria-label="Editar">
                        <Pencil size={14} strokeWidth={1.5} />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => onExcluir(item)} disabled={bloqueada} aria-label="Remover">
                        <Trash2 size={14} strokeWidth={1.5} />
                      </Button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
