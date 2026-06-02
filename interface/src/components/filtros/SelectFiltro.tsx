"use client"

import type { ReactNode } from "react"

/** Select nativo rotulado, padrão das toolbars do painel. Antes duplicado inline
 *  em atendimentos/page.tsx e clientes/page.tsx. */
export function SelectFiltro({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {children}
      </select>
    </label>
  )
}
