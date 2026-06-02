"use client"

export function HeaderDashboard() {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
          Dashboard
        </h1>
        <p className="mt-1 text-[13px] text-text-muted">
          Resultado, operação e financeiro da Elite Baby no período selecionado.
        </p>
      </div>
    </header>
  )
}
