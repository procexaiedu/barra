"use client"

import { cn } from "@/lib/utils"
import type { AbaModelo } from "@/tipos/modelos"

const abas = [
  { slug: "perfil" as const, label: "Perfil" },
  { slug: "faq" as const, label: "Dúvidas" },
  { slug: "midia" as const, label: "Fotos e vídeos" },
]

export function AbasModelo({
  aba,
  onChange,
}: {
  aba: AbaModelo
  onChange: (aba: AbaModelo) => void
}) {
  return (
    <div role="tablist" aria-label="Abas da modelo" className="flex gap-1 border-b border-border">
      {abas.map((item) => {
        const active = item.slug === aba
        return (
          <button
            key={item.slug}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.slug)}
            className={cn(
              "relative px-3 pb-2.5 pt-1 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              active
                ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-gold-500"
                : "text-text-muted hover:text-text-secondary"
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
