"use client"

import { ImageIcon, Video, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { MidiaItem } from "@/tipos/modelos"

export function ItemMidia({
  item,
  onOpen,
  onToggleAprovada,
  onDelete,
}: {
  item: MidiaItem
  onOpen: () => void
  onToggleAprovada: () => void
  onDelete: () => void
}) {
  const Icon = item.tipo === "video" ? Video : ImageIcon
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={onOpen}
        className="flex aspect-square w-full items-center justify-center bg-ink-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
      >
        {item.tipo === "foto" ? (
          <img src={item.url_assinada} alt={item.tag} className="h-full w-full object-cover" />
        ) : (
          <div className="flex flex-col items-center gap-2 text-text-muted">
            <Icon size={28} strokeWidth={1.5} />
            <span className="text-xs">Video</span>
          </div>
        )}
      </button>
      <div className="space-y-3 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium text-text-primary">{item.tag}</span>
          <span className="rounded-full bg-ink-300 px-2 py-1 text-xs text-text-muted">
            {item.aprovada ? "pronta" : "oculta"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onToggleAprovada}>
            {item.aprovada ? "Ocultar" : "Liberar"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete}>
            <Trash2 size={14} strokeWidth={1.5} />
            Remover
          </Button>
        </div>
      </div>
    </article>
  )
}
