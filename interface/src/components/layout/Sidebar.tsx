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
  PanelLeft,
  PanelLeftClose,
} from "lucide-react"
import { supabase } from "@/lib/supabase"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ThemeToggle } from "@/components/layout/ThemeToggle"

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
      { href: "/clientes", label: "Clientes", icon: Users },
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
  const [collapsed, setCollapsed] = useState(false)

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
    <TooltipProvider delay={400}>
      <aside
        className={cn(
          "flex flex-col border-r border-border bg-background overflow-x-hidden transition-[width] duration-200 ease-in-out max-lg:hidden",
          collapsed ? "w-[60px]" : "w-60"
        )}
      >
        <div
          className={cn(
            "flex items-center py-6",
            collapsed ? "justify-center px-0" : "justify-between px-6"
          )}
        >
          {!collapsed && (
            <span className="font-serif text-[28px] font-medium text-gold-500 whitespace-nowrap">
              Barra Vips
            </span>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
            className="flex size-8 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-accent hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {collapsed ? (
              <PanelLeft size={16} strokeWidth={1.5} />
            ) : (
              <PanelLeftClose size={16} strokeWidth={1.5} />
            )}
          </button>
        </div>

        <nav aria-label="Navegação principal" className="flex-1 overflow-y-auto overflow-x-hidden px-3">
          {grupos.map((grupo) => (
            <div key={grupo.label} className="mb-4">
              {collapsed ? (
                <div className="mb-1 h-4" />
              ) : (
                <h3 className="mb-1 px-3 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted whitespace-nowrap">
                  {grupo.label}
                </h3>
              )}
              {grupo.items.map((item) => {
                const Icon = item.icon
                const active = isActive(item.href)
                const linkClass = cn(
                  "flex h-10 items-center rounded-md py-2 text-sm transition-colors",
                  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
                  collapsed ? "w-full justify-center px-0" : "gap-3 px-3",
                  active
                    ? "bg-accent text-text-brand"
                    : "text-text-secondary hover:bg-accent hover:text-text-primary"
                )

                if (collapsed) {
                  return (
                    <Tooltip key={item.href}>
                      <TooltipTrigger render={<Link href={item.href} className={linkClass} />}>
                        <Icon size={20} strokeWidth={1.5} />
                      </TooltipTrigger>
                      <TooltipContent side="right">{item.label}</TooltipContent>
                    </Tooltip>
                  )
                }

                return (
                  <Link key={item.href} href={item.href} className={linkClass}>
                    <Icon size={20} strokeWidth={1.5} />
                    <span className="whitespace-nowrap">{item.label}</span>
                  </Link>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-border px-3 py-3">
          {!collapsed && (
            <p className="mb-2 truncate px-3 text-xs font-medium text-text-muted">
              {email ?? "Sessão ativa"}
            </p>
          )}
          <ThemeToggle collapsed={collapsed} />
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    onClick={handleLogout}
                    className={cn(
                      "flex h-10 w-full items-center justify-center rounded-md py-2 text-sm text-text-secondary transition-colors",
                      "hover:bg-accent hover:text-text-primary",
                      "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
                    )}
                  />
                }
              >
                <LogOut size={16} strokeWidth={1.5} />
              </TooltipTrigger>
              <TooltipContent side="right">Sair</TooltipContent>
            </Tooltip>
          ) : (
            <button
              onClick={handleLogout}
              className={cn(
                "flex h-10 w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-text-secondary transition-colors",
                "hover:bg-accent hover:text-text-primary",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
              )}
            >
              <LogOut size={16} strokeWidth={1.5} />
              <span>Sair</span>
            </button>
          )}
        </div>
      </aside>
    </TooltipProvider>
  )
}
