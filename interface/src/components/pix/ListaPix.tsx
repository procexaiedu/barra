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
  carregandoMais,
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
  carregandoMais: boolean
  onSelect: (id: string) => void
  onRetry: () => void
  onCarregarMais: () => void
}) {
  return (
    <section aria-label="Lista de Pix" className="min-w-0">
      <div className="overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10">
        {status === "loading" ? (
          <div aria-busy="true" className="flex flex-col gap-px">
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
                <Button
                  variant="ghost"
                  className="w-full"
                  onClick={onCarregarMais}
                  disabled={carregandoMais}
                >
                  {carregandoMais ? "Carregando…" : "Carregar mais"}
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
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
        <Inbox size={22} strokeWidth={1.75} className="text-text-muted" />
      </div>
      <div>
        <p className="text-sm font-medium text-text-primary">
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
