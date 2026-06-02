"use client"

export function Observacoes({ texto }: { texto: string | null }) {
  if (!texto) return null

  return (
    <section aria-label="Observações internas" className="rounded-lg border border-border bg-card p-5">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        Observações
      </p>
      <p className="text-sm leading-relaxed text-text-primary">{texto}</p>
    </section>
  )
}
