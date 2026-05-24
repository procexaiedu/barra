"use client"

import { useEffect, useState } from "react"
import { useTheme } from "next-themes"
import { Sun, Moon, Monitor } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

const proximoTema: Record<string, string> = {
  light: "dark",
  dark: "system",
  system: "light",
}

const rotuloTema: Record<string, string> = {
  light: "Tema claro",
  dark: "Tema escuro",
  system: "Tema do sistema",
}

export function ThemeToggle({ collapsed }: { collapsed: boolean }) {
  const { theme, setTheme } = useTheme()
  const [montado, setMontado] = useState(false)

  useEffect(() => {
    // Hydration guard (padrão next-themes): só revela o tema real após montar no
    // client. A regra abaixo é falso-positivo para este padrão de "montado".
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMontado(true)
  }, [])

  const temaAtual = (montado && theme) || "system"
  const Icone = temaAtual === "light" ? Sun : temaAtual === "dark" ? Moon : Monitor
  const proximo = proximoTema[temaAtual] ?? "light"
  const rotulo = rotuloTema[temaAtual] ?? "Tema"

  const acao = () => setTheme(proximo)

  const buttonClass = cn(
    "flex h-10 items-center rounded-md py-2 text-sm text-text-secondary transition-colors",
    "hover:bg-accent hover:text-text-primary",
    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
    collapsed ? "w-full justify-center px-0" : "w-full gap-3 px-3",
  )

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              onClick={acao}
              aria-label={`Alternar tema (atual: ${rotulo.toLowerCase()})`}
              className={buttonClass}
            />
          }
        >
          <Icone size={16} strokeWidth={1.5} suppressHydrationWarning />
        </TooltipTrigger>
        <TooltipContent side="right">{rotulo}</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <button
      type="button"
      onClick={acao}
      aria-label={`Alternar tema (atual: ${rotulo.toLowerCase()})`}
      className={buttonClass}
    >
      <Icone size={16} strokeWidth={1.5} suppressHydrationWarning />
      <span suppressHydrationWarning>{rotulo}</span>
    </button>
  )
}
