"use client"

export function Observacoes({ texto }: { texto: string | null }) {
  if (!texto) return null

  return (
    <section aria-label="Observações internas" className="rounded-lg border border-border bg-card p-5 shadow-elev-1 ring-1 ring-border-subtle">
      <h2 className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        <span className="h-3 w-0.5 rounded-full bg-gold-500" aria-hidden />
        Observações
      </h2>
      <p className="text-sm leading-relaxed text-text-primary">{texto}</p>
    </section>
  )
}
