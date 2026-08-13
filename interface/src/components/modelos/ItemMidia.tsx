"use client"

import Image from "next/image"
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
    <article className="group relative overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle transition-all hover:-translate-y-px hover:shadow-elev-2 hover:ring-border-brand/40">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Abrir ${item.tag}`}
        className="relative flex aspect-square w-full items-center justify-center bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        {item.tipo === "foto" ? (
          // A URL assinada aponta para o ORIGINAL no MinIO (o upload não limita tamanho), e o
          // quadradinho tem ~200-300px: sem o otimizador, abrir a aba baixaria dezenas de arquivos
          // cheios. O servidor baixa o original uma vez e entrega ao browser só a versão do tamanho
          // pedido. `fill` porque o backend não devolve as dimensões da mídia.
          <Image
            src={item.url_assinada}
            alt={item.tag}
            fill
            sizes="(min-width: 1280px) 25vw, (min-width: 640px) 33vw, 50vw"
            className="object-cover"
          />
        ) : (
          <div className="flex flex-col items-center gap-1.5 text-text-muted">
            <Icon size={24} strokeWidth={1.5} />
            <span className="text-[11px] uppercase tracking-wider">Vídeo</span>
          </div>
        )}
        {!item.aprovada && (
          // O fundo é fixo (véu escuro sobre a miniatura, não troca com o tema), então o texto
          // também precisa ser: `text-text-muted` escurece no tema claro e cai para ~3:1.
          <span className="absolute left-2 top-2 rounded bg-ink-0/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-ink-800 backdrop-blur-sm">
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
