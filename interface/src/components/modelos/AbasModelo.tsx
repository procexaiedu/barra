"use client"

import { FileQuestion, Images, UserRound } from "lucide-react"
import { cn } from "@/lib/utils"
import type { AbaModelo } from "@/tipos/modelos"

const abas = [
  { slug: "perfil" as const, label: "Perfil", icon: UserRound },
  { slug: "faq" as const, label: "Duvidas", icon: FileQuestion },
  { slug: "midia" as const, label: "Fotos e videos", icon: Images },
]

export function AbasModelo({
  aba,
  onChange,
}: {
  aba: AbaModelo
  onChange: (aba: AbaModelo) => void
}) {
  return (
    <div role="tablist" aria-label="Abas da modelo" className="flex flex-wrap gap-2 border-b border-border pb-3">
      {abas.map((item) => {
        const Icon = item.icon
        const active = item.slug === aba
        return (
          <button
            key={item.slug}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.slug)}
            className={cn(
              "inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
              active
                ? "bg-ink-200 text-gold-500"
                : "text-text-secondary hover:bg-ink-200 hover:text-text-primary"
            )}
          >
            <Icon size={16} strokeWidth={1.5} />
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
