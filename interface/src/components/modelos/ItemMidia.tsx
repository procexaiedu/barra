"use client"

import { Eye, EyeOff, ImageIcon, Trash2, Video } from "lucide-react"
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
    <article className="group relative overflow-hidden rounded-lg bg-card ring-1 ring-foreground/10">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Abrir ${item.tag}`}
        className="relative flex aspect-square w-full items-center justify-center bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        {item.tipo === "foto" ? (
          // URL assinada do MinIO com expiry; next/image precisaria de loader customizado.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.url_assinada} alt={item.tag} loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="flex flex-col items-center gap-1.5 text-text-muted">
            <Icon size={24} strokeWidth={1.5} />
            <span className="text-[11px] uppercase tracking-wider">Vídeo</span>
          </div>
        )}
        {!item.aprovada && (
          <span className="absolute left-2 top-2 rounded bg-ink-0/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text-muted backdrop-blur-sm">
            Inativa
          </span>
        )}
      </button>
      <div className="flex items-center justify-between gap-2 px-2.5 py-2">
        <span className={`truncate text-xs font-medium ${item.tag ? "text-text-secondary" : "italic text-text-muted"}`}>{item.tag || "Sem tag"}</span>
        <div className="flex shrink-0 gap-0.5">
          <Button variant="ghost" size="icon-xs" onClick={onToggleAprovada} aria-label={item.aprovada ? "Inativar" : "Ativar"}>
            {item.aprovada ? <EyeOff size={12} strokeWidth={1.5} /> : <Eye size={12} strokeWidth={1.5} />}
          </Button>
          <Button variant="ghost" size="icon-xs" onClick={onDelete} aria-label="Remover" className="text-text-muted hover:text-state-lost">
            <Trash2 size={12} strokeWidth={1.5} />
          </Button>
        </div>
      </div>
    </article>
  )
}
