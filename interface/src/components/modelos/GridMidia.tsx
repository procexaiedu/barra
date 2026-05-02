"use client"

import { Images } from "lucide-react"
import { ItemMidia } from "@/components/modelos/ItemMidia"
import type { MidiaItem } from "@/tipos/modelos"

export function GridMidia({
  items,
  onOpen,
  onToggleAprovada,
  onDelete,
}: {
  items: MidiaItem[]
  onOpen: (item: MidiaItem) => void
  onToggleAprovada: (item: MidiaItem) => void
  onDelete: (item: MidiaItem) => void
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex gap-3">
          <Images className="mt-0.5 text-text-muted" size={20} strokeWidth={1.5} />
          <div>
            <p className="text-sm text-text-primary">Nenhuma midia cadastrada.</p>
            <p className="mt-1 text-[13px] text-text-muted">Adicione fotos ou videos prontos para o atendimento.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <section aria-label="Midia da modelo" className="grid grid-cols-2 gap-4 xl:grid-cols-3">
      {items.map((item) => (
        <ItemMidia
          key={item.id}
          item={item}
          onOpen={() => onOpen(item)}
          onToggleAprovada={() => onToggleAprovada(item)}
          onDelete={() => onDelete(item)}
        />
      ))}
    </section>
  )
}
