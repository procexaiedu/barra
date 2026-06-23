"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Menu } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  destinosPrincipais,
  destinosSecundarios,
  itemAtivo,
} from "@/components/layout/navegacao"
import { useMobileNav } from "@/components/layout/MobileNavContext"

export function BottomNav() {
  const pathname = usePathname()
  const { drawerAberto, abrirDrawer } = useMobileNav()

  // "Mais" fica destacado quando a rota atual é uma das secundárias.
  const emRotaSecundaria = destinosSecundarios.some((item) =>
    itemAtivo(item.href, pathname)
  )

  const itemClass = (ativo: boolean) =>
    cn(
      "relative flex min-h-[44px] flex-1 flex-col items-center justify-center gap-0.5 text-[10px] transition-colors",
      "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
      ativo
        ? "text-text-brand before:absolute before:top-0 before:h-[2px] before:w-9 before:rounded-b-full before:bg-gold-500 before:content-['']"
        : "text-text-secondary"
    )

  return (
    <nav
      aria-label="Navegação principal (mobile)"
      className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-background/95 backdrop-blur-sm pb-[env(safe-area-inset-bottom)] shadow-[0_-4px_16px_-6px_rgb(20_20_20/0.16)] dark:shadow-[0_-4px_18px_-4px_rgb(0_0_0/0.6)] lg:hidden"
    >
      {destinosPrincipais.map((item) => {
        const Icon = item.icon
        const ativo = itemAtivo(item.href, pathname)
        return (
          <Link key={item.href} href={item.href} className={itemClass(ativo)}>
            <Icon size={20} strokeWidth={1.5} />
            <span className="whitespace-nowrap">{item.label}</span>
          </Link>
        )
      })}
      <button
        type="button"
        onClick={abrirDrawer}
        aria-label="Mais opções"
        aria-expanded={drawerAberto}
        className={itemClass(emRotaSecundaria || drawerAberto)}
      >
        <Menu size={20} strokeWidth={1.5} />
        <span>Mais</span>
      </button>
    </nav>
  )
}
