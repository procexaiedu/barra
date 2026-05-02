"use client"

import { useState } from "react"
import { Check, Loader2, Pencil, Plus, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatBRL } from "@/lib/formatters"
import type { Duracao, Programa, ProgramaModeloVinculo } from "@/tipos/modelos"

export function ProgramasModelo({
  catalogo,
  duracoes,
  vinculados,
  onVincular,
  onAtualizarPreco,
  onDesvincular,
}: {
  catalogo: Programa[]
  duracoes: Duracao[]
  vinculados: ProgramaModeloVinculo[]
  onVincular: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  if (catalogo.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-card p-6">
        <h2 className="mb-2 text-base font-semibold text-text-primary">Serviços e preços</h2>
        <p className="text-sm text-text-muted">
          Nenhum programa cadastrado no catálogo da agência. Acesse a aba{" "}
          <strong>Programas</strong> para adicionar.
        </p>
      </section>
    )
  }

  const vinculadosMap = new Map(
    vinculados.map((v) => [`${v.programa_id}:${v.duracao_id}`, v]),
  )

  const grupos = agrupar(catalogo)

  return (
    <section className="rounded-lg border border-border bg-card p-6">
      <div className="mb-5">
        <h2 className="text-base font-semibold text-text-primary">Serviços e preços</h2>
        <p className="mt-1 text-sm text-text-muted">
          Defina o preço desta modelo por programa e duração. Deixe em branco os que ela não oferece.
        </p>
      </div>

      <div className="space-y-6">
        {grupos.map(({ titulo, items }) => (
          <div key={titulo ?? "__geral__"}>
            {titulo && (
              <p className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
                {titulo}
              </p>
            )}
            <div className="space-y-3">
              {items.map((programa) => (
                <CardProgramaModelo
                  key={programa.id}
                  programa={programa}
                  duracoes={duracoes}
                  vinculadosMap={vinculadosMap}
                  onVincular={onVincular}
                  onAtualizarPreco={onAtualizarPreco}
                  onDesvincular={onDesvincular}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function CardProgramaModelo({
  programa,
  duracoes,
  vinculadosMap,
  onVincular,
  onAtualizarPreco,
  onDesvincular,
}: {
  programa: Programa
  duracoes: Duracao[]
  vinculadosMap: Map<string, ProgramaModeloVinculo>
  onVincular: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  return (
    <div className="rounded-lg border border-border bg-ink-100">
      <div className="px-4 py-2.5 border-b border-border">
        <h3 className="text-sm font-semibold text-text-primary">{programa.nome}</h3>
      </div>
      <div className="divide-y divide-border">
        {duracoes.map((duracao) => {
          const vinculo = vinculadosMap.get(`${programa.id}:${duracao.id}`) ?? null
          return (
            <LinhaDuracao
              key={duracao.id}
              programa={programa}
              duracao={duracao}
              vinculo={vinculo}
              onVincular={onVincular}
              onAtualizarPreco={onAtualizarPreco}
              onDesvincular={onDesvincular}
            />
          )
        })}
      </div>
    </div>
  )
}

function LinhaDuracao({
  programa,
  duracao,
  vinculo,
  onVincular,
  onAtualizarPreco,
  onDesvincular,
}: {
  programa: Programa
  duracao: Duracao
  vinculo: ProgramaModeloVinculo | null
  onVincular: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onAtualizarPreco: (programaId: string, duracaoId: string, preco: number) => Promise<void>
  onDesvincular: (programaId: string, duracaoId: string) => Promise<void>
}) {
  const [editando, setEditando] = useState(false)
  const [precoInput, setPrecoInput] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const abrirEdicao = () => {
    setPrecoInput(vinculo ? String(vinculo.preco) : "")
    setEditando(true)
  }

  const cancelar = () => {
    setEditando(false)
    setPrecoInput("")
  }

  const confirmar = async () => {
    const preco = Number(precoInput)
    if (!precoInput.trim() || isNaN(preco) || preco < 0) {
      toast.error("Informe um preço válido")
      return
    }
    setSubmitting(true)
    try {
      if (vinculo) {
        await onAtualizarPreco(programa.id, duracao.id, preco)
        toast.success("Preço atualizado")
      } else {
        await onVincular(programa.id, duracao.id, preco)
        toast.success("Programa adicionado")
      }
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
      await onDesvincular(programa.id, duracao.id)
      setEditando(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao remover")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5">
      <span className="text-sm text-text-muted w-24 shrink-0">{duracao.nome}</span>

      <div className="flex items-center gap-2 ml-auto">
        {editando ? (
          <>
            <Input
              type="number"
              min={0}
              step={50}
              value={precoInput}
              onChange={(e) => setPrecoInput(e.target.value)}
              placeholder="Ex.: 800"
              className="h-8 w-28 bg-input text-sm"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmar()
                if (e.key === "Escape") cancelar()
              }}
            />
            <Button variant="primary" size="sm" onClick={confirmar} disabled={submitting}>
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2} />}
            </Button>
            <Button variant="ghost" size="sm" onClick={cancelar} disabled={submitting}>
              <X size={14} strokeWidth={1.5} />
            </Button>
          </>
        ) : (
          <>
            {vinculo ? (
              <>
                <span className="text-sm font-medium tabular-nums text-text-primary">
                  {formatBRL(vinculo.preco)}
                </span>
                <Button variant="ghost" size="sm" onClick={abrirEdicao} disabled={submitting}>
                  <Pencil size={14} strokeWidth={1.5} />
                </Button>
                <Button variant="ghost" size="sm" onClick={remover} disabled={submitting}>
                  {submitting ? <Loader2 size={14} className="animate-spin" /> : <X size={14} strokeWidth={1.5} />}
                </Button>
              </>
            ) : (
              <Button variant="ghost" size="sm" onClick={abrirEdicao} disabled={submitting}>
                <Plus size={14} strokeWidth={1.5} />
                Definir preço
              </Button>
            )}
          </>
        )}
      </div>
    </div>
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
