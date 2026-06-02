"use client"

import { Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
    <section aria-label="Lista de modelos" className="flex flex-col gap-2">
      <ul className="flex flex-col gap-1.5">
        {items.map((item) => (
          <li key={item.id}>
            <ItemModelo
              item={item}
              selected={item.id === selectedId}
              onSelect={() => onSelect(item.id)}
            />
          </li>
        ))}
      </ul>
      {nextCursor && (
        <Button variant="ghost" size="sm" onClick={onCarregarMais} className="w-full">
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
    <Card>
      <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
        <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
          <Users size={22} strokeWidth={1.75} className="text-text-muted" />
        </div>
        <div>
          <p className="text-sm font-medium text-text-primary">
            {filtrosAplicados ? "Nenhuma modelo encontrada." : "Nenhuma modelo cadastrada."}
          </p>
          <p className="mt-1 text-[13px] text-text-muted">
            {filtrosAplicados
              ? "Ajuste situação, WhatsApp ou local de atendimento."
              : "Adicione a primeira modelo para começar a operar."}
          </p>
        </div>
        {!filtrosAplicados && (
          <Button variant="outline" size="sm" onClick={onAdicionar}>
            Adicionar modelo
          </Button>
        )}
      </div>
    </Card>
  )
}

function ListaSkeleton() {
  return (
    <section aria-label="Lista de modelos" aria-busy="true" className="flex flex-col gap-1.5">
      {Array.from({ length: 4 }).map((_, index) => (
        <Skeleton key={index} className="h-[68px] rounded-lg" />
      ))}
    </section>
  )
}
