"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LogOut } from "lucide-react"
import { supabase } from "@/lib/supabase"
import { cn } from "@/lib/utils"
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { grupos, itemAtivo } from "@/components/layout/navegacao"
import { useMobileNav } from "@/components/layout/MobileNavContext"

export function MobileDrawer() {
  const pathname = usePathname()
  const { drawerAberto, setDrawerAberto, fecharDrawer } = useMobileNav()
  const [email, setEmail] = useState<string | null>(null)

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null)
    })
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setEmail(session?.user.email ?? null)
    })
    return () => sub.subscription.unsubscribe()
  }, [])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    window.location.assign("/login")
  }

  return (
    <Sheet open={drawerAberto} onOpenChange={setDrawerAberto}>
      <SheetContent side="left" className="w-[min(86vw,20rem)] lg:hidden">
        <SheetHeader className="px-6 py-5">
          <SheetTitle className="font-serif text-[24px] font-medium text-gold-500">
            Elite Baby
          </SheetTitle>
        </SheetHeader>

        <SheetBody className="px-3 py-3">
          {grupos.map((grupo) => (
            <div key={grupo.label} className="mb-4">
              <h3 className="mb-1 px-3 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
                {grupo.label}
              </h3>
              {grupo.items.map((item) => {
                const Icon = item.icon
                const ativo = itemAtivo(item.href, pathname)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={fecharDrawer}
                    className={cn(
                      "flex h-11 items-center gap-3 rounded-md px-3 text-sm transition-colors",
                      "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                      ativo
                        ? "bg-accent text-text-brand"
                        : "text-text-secondary hover:bg-accent hover:text-text-primary"
                    )}
                  >
                    <Icon size={20} strokeWidth={1.5} />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </div>
          ))}
        </SheetBody>

        <div className="border-t border-border px-3 py-3">
          <p className="mb-2 truncate px-3 text-xs font-medium text-text-muted">
            {email ?? "Sessão ativa"}
          </p>
          <ThemeToggle collapsed={false} />
          <button
            onClick={handleLogout}
            className={cn(
              "flex h-11 w-full items-center gap-3 rounded-md px-3 text-sm text-text-secondary transition-colors",
              "hover:bg-accent hover:text-text-primary",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            )}
          >
            <LogOut size={16} strokeWidth={1.5} />
            <span>Sair</span>
          </button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
