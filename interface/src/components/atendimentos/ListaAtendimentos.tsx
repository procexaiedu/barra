"use client"

import { Inbox } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import type { AtendimentoListaItem } from "@/tipos/atendimentos"
import { ItemAtendimento } from "@/components/atendimentos/ItemAtendimento"

export function ListaAtendimentos({
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
  items: AtendimentoListaItem[]
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
    <section aria-label="Lista de atendimentos" className="min-w-0">
      <div className="overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle">
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
              <ItemAtendimento
                key={item.id}
                item={item}
                selected={item.id === selectedId}
                onSelect={onSelect}
              />
            ))}
            {nextCursor && (
              <div className="p-2">
                <Button variant="ghost" size="sm" className="w-full text-text-muted hover:text-text-primary" onClick={onCarregarMais}>
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
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
        <Inbox size={22} strokeWidth={1.75} className="text-text-muted" />
      </div>
      <div>
        <p className="text-sm font-medium text-text-primary">
          {filtrosAplicados ? "Nenhum atendimento encontrado para estes filtros." : "Nenhum atendimento aberto."}
        </p>
        <p className="mt-1 text-[13px] text-text-muted">
          {filtrosAplicados
            ? "Ajuste os filtros para ampliar a busca."
            : "Novos atendimentos aparecem quando clientes chamarem no WhatsApp da modelo."}
        </p>
      </div>
    </div>
  )
}
