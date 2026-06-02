"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/** Campo de busca padrão das toolbars (rótulo "Buscar" + ícone à esquerda).
 *  Antes duplicado inline em Atendimentos, Clientes, Modelos e Pix. O `className`
 *  controla a largura/crescimento no contexto de cada toolbar (ex.: "flex-1",
 *  "min-w-72 flex-1"). */
export function BuscaFiltro({
  value,
  onChange,
  placeholder = "Buscar",
  className,
  ariaLabel,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  ariaLabel?: string
}) {
  return (
    <label className={cn("relative flex flex-col gap-1", className)}>
      <span className="text-xs font-medium text-text-muted">Buscar</span>
      <Search
        size={16}
        strokeWidth={1.5}
        className="pointer-events-none absolute left-3 bottom-2.5 text-text-muted"
      />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel ?? placeholder}
        className="h-9 pl-9"
      />
    </label>
  )
}
