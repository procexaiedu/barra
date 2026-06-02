"use client"

import { Images } from "lucide-react"
import { Card } from "@/components/ui/card"
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
      <Card>
        <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
          <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
            <Images size={22} strokeWidth={1.75} className="text-text-muted" />
          </div>
          <div>
            <p className="text-sm font-medium text-text-primary">Nenhuma mídia cadastrada.</p>
            <p className="mt-1 text-[13px] text-text-muted">Adicione fotos ou vídeos prontos para o atendimento.</p>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <section aria-label="Mídia da modelo" className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
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
