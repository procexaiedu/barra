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
              <ItemAtendimento
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
          {filtrosAplicados ? "Nenhum atendimento encontrado para estes filtros." : "Nenhum atendimento aberto."}
        </p>
        <p className="mt-1 text-[13px] text-text-muted">
          {filtrosAplicados
            ? "Ajuste busca, estado, tipo, urgência ou pausa da IA."
            : "Novos atendimentos aparecem quando clientes chamarem no WhatsApp da modelo."}
        </p>
      </div>
    </div>
  )
}
