"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  MessagesSquare,
  Calendar,
  Receipt,
  Users,
  IdCard,
  ChartLine,
  LogOut,
} from "lucide-react"
import { supabase } from "@/lib/supabase"
import { cn } from "@/lib/utils"

const grupos = [
  {
    label: "OPERAÇÃO",
    items: [
      { href: "/", label: "Painel", icon: LayoutDashboard },
      { href: "/atendimentos", label: "Atendimentos", icon: MessagesSquare },
      { href: "/agenda", label: "Agenda", icon: Calendar },
      { href: "/pix", label: "Pix", icon: Receipt },
    ],
  },
  {
    label: "CADASTROS",
    items: [
      { href: "/crm", label: "CRM", icon: Users },
      { href: "/modelos", label: "Modelos", icon: IdCard },
    ],
  },
  {
    label: "ANÁLISE",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: ChartLine },
    ],
  },
]

export function Sidebar() {
  const pathname = usePathname()
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

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/"
    return pathname.startsWith(href)
  }

  const handleLogout = async () => {
    await supabase.auth.signOut()
    window.location.assign("/login")
  }

  return (
    <aside className="flex h-full w-60 flex-col border-r border-border bg-background max-lg:hidden">
      <div className="px-6 py-6">
        <span className="font-serif text-[28px] font-medium text-gold-500">
          Barra Vips
        </span>
      </div>

      <nav aria-label="Navegação principal" className="flex-1 overflow-y-auto px-3">
        {grupos.map((grupo) => (
          <div key={grupo.label} className="mb-4">
            <h3 className="mb-1 px-3 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
              {grupo.label}
            </h3>
            {grupo.items.map((item) => {
              const Icon = item.icon
              const active = isActive(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
                    active
                      ? "bg-ink-200 text-gold-500"
                      : "text-text-secondary hover:bg-ink-200 hover:text-text-primary"
                  )}
                >
                  <Icon size={20} strokeWidth={1.5} />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border px-3 py-3">
        <p className="mb-2 truncate px-3 text-xs font-medium text-text-muted">
          {email ?? "Sessão ativa"}
        </p>
        <button
          onClick={handleLogout}
          className={cn(
            "flex h-10 w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary transition-colors",
            "hover:bg-ink-200 hover:text-text-primary",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
          )}
        >
          <LogOut size={16} strokeWidth={1.5} />
          <span>Sair</span>
        </button>
      </div>
    </aside>
  )
}
