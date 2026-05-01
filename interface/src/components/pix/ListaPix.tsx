"use client"

import { Inbox } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import type { PixListaItem } from "@/tipos/pix"
import { ItemPix } from "./ItemPix"

export function ListaPix({
  items,
  selectedId,
  status,
  error,
  filtrosAplicados,
  nextCursor,
  onSelect,
  onRetry,
  onCarregarMais,
}: {
  items: PixListaItem[]
  selectedId: string | null
  status: "loading" | "success" | "error"
  error: string | null
  filtrosAplicados: boolean
  nextCursor: string | null
  onSelect: (id: string) => void
  onRetry: () => void
  onCarregarMais: () => void
}) {
  return (
    <section aria-label="Lista de Pix" className="min-w-0">
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {status === "loading" ? (
          <div aria-busy="true" className="space-y-px">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-[88px] rounded-none" />
            ))}
          </div>
        ) : status === "error" ? (
          <div className="p-4">
            <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
          </div>
        ) : items.length === 0 ? (
          <EmptyLista filtrosAplicados={filtrosAplicados} />
        ) : (
          <div className="divide-y divide-border">
            {items.map((item) => (
              <ItemPix
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                onSelect={onSelect}
              />
            ))}
            {nextCursor && (
              <div className="p-3">
                <Button variant="ghost" className="w-full" onClick={onCarregarMais}>
                  Carregar mais
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function EmptyLista({ filtrosAplicados }: { filtrosAplicados: boolean }) {
  return (
    <div className="flex min-h-[220px] items-start gap-3 p-6">
      <Inbox size={20} strokeWidth={1.5} className="mt-0.5 text-text-muted" />
      <div>
        <p className="text-sm text-text-primary">
          {filtrosAplicados
            ? "Nenhum Pix encontrado para estes filtros."
            : "Nenhum Pix aguardando decisão."}
        </p>
        <p className="mt-1 text-[13px] text-text-muted">
          {filtrosAplicados
            ? "Ajuste os filtros para ampliar a busca."
            : "Pix duvidosos aparecem aqui assim que precisarem da sua decisão."}
        </p>
      </div>
    </div>
  )
}
