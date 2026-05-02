"use client"

import { formatRangeAbsoluto } from "./utils"

interface Props {
  de: string | null
  ate: string | null
}

export function HeaderDashboard({ de, ate }: Props) {
  return (
    <header className="flex items-baseline justify-between gap-4">
      <h1 className="font-serif text-[40px] font-medium leading-[48px] text-text-primary">
        Dashboard
      </h1>
      {de && ate ? (
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
            Período
          </span>
          <span className="font-mono text-[13px] text-text-primary">
            {formatRangeAbsoluto(de, ate)}
          </span>
        </div>
      ) : null}
    </header>
  )
}
