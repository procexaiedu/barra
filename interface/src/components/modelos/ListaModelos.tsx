"use client"

import { Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { ItemModelo } from "@/components/modelos/ItemModelo"
import type { ModeloListaItem } from "@/tipos/modelos"

export function ListaModelos({
  items,
  selectedId,
  status,
  error,
  filtrosAplicados,
  nextCursor,
  onRetry,
  onAdicionar,
  onSelect,
  onCarregarMais,
}: {
  items: ModeloListaItem[]
  selectedId: string | null
  status: "loading" | "success" | "error"
  error: string | null
  filtrosAplicados: boolean
  nextCursor: string | null
  onRetry: () => void
  onAdicionar: () => void
  onSelect: (id: string) => void
  onCarregarMais: () => void
}) {
  if (status === "loading") return <ListaSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (items.length === 0) return <EmptyLista filtrosAplicados={filtrosAplicados} onAdicionar={onAdicionar} />

  return (
    <section aria-label="Lista de modelos" className="space-y-3">
      {items.map((item) => (
        <ItemModelo
          key={item.id}
          item={item}
          selected={item.id === selectedId}
          onSelect={() => onSelect(item.id)}
        />
      ))}
      {nextCursor && (
        <Button variant="ghost" onClick={onCarregarMais} className="w-full">
          Carregar mais
        </Button>
      )}
    </section>
  )
}

function EmptyLista({
  filtrosAplicados,
  onAdicionar,
}: {
  filtrosAplicados: boolean
  onAdicionar: () => void
}) {
  return (
    <section aria-label="Lista de modelos" className="rounded-lg border border-border bg-card p-6">
      <div className="flex gap-3">
        <Users className="mt-0.5 text-text-muted" size={20} strokeWidth={1.5} />
        <div>
          <p className="text-sm text-text-primary">
            {filtrosAplicados ? "Nenhuma modelo encontrada para estes filtros." : "Nenhuma modelo cadastrada."}
          </p>
          <p className="mt-1 text-[13px] text-text-muted">
            {filtrosAplicados
              ? "Ajuste situação, WhatsApp ou local de atendimento."
              : "Adicione a primeira modelo para começar a operar."}
          </p>
          {!filtrosAplicados && (
            <Button variant="primary" onClick={onAdicionar} className="mt-4">
              Adicionar modelo
            </Button>
          )}
        </div>
      </div>
    </section>
  )
}

function ListaSkeleton() {
  return (
    <section aria-label="Lista de modelos" aria-busy="true" className="space-y-3">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-24 rounded-lg" />
      ))}
    </section>
  )
}
