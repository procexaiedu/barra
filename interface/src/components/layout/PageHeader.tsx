import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"

interface PageHeaderAction {
  label: string
  onClick: () => void
  icon?: ReactNode
}

/** Cabeçalho padrão de cada módulo do painel: título (serif 32px) + descrição
 *  curta + canto superior direito. O canto direito recebe a ação primária
 *  (`action` → Button variant="primary") e/ou `children` (toggle de visão,
 *  filtros de variável do header). Estrutura espelhada de `clientes/page.tsx`,
 *  a referência visual. */
export function PageHeader({
  title,
  description,
  action,
  children,
}: {
  title: string
  description: string
  action?: PageHeaderAction
  children?: ReactNode
}) {
  const botaoAcao = action ? (
    <Button variant="primary" onClick={action.onClick}>
      {action.icon}
      {action.label}
    </Button>
  ) : null

  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[26px] font-medium leading-tight tracking-[-0.01em] text-text-primary sm:text-[32px]">
          {title}
        </h1>
        <p className="mt-1 text-[13px] text-text-muted">{description}</p>
      </div>
      {(children || botaoAcao) && (
        <div className="flex flex-wrap items-end gap-2">
          {children}
          {botaoAcao}
        </div>
      )}
    </header>
  )
}
