"use client"

import { PERFIS_FISICOS, PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import type { PerfilFisico } from "@/tipos/clientes"

/** Multi-seleção por chips toggle (reusa o padrão do SeletorConversa). Usado no
 *  cadastro/edição do cliente e no filtro da lista. ADR 0006. */
export function SeletorPerfis({
  value,
  onChange,
  disabled = false,
  idPrefix = "perfil",
}: {
  value: PerfilFisico[]
  onChange: (next: PerfilFisico[]) => void
  disabled?: boolean
  idPrefix?: string
}) {
  const toggle = (slug: PerfilFisico) => {
    if (disabled) return
    onChange(value.includes(slug) ? value.filter((p) => p !== slug) : [...value, slug])
  }
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Perfil físico preferido">
      {PERFIS_FISICOS.map((slug) => {
        const ativo = value.includes(slug)
        return (
          <button
            key={slug}
            type="button"
            id={`${idPrefix}-${slug}`}
            aria-pressed={ativo}
            disabled={disabled}
            onClick={() => toggle(slug)}
            className={
              ativo
                ? "rounded-full border border-state-active bg-accent px-3 py-1 text-xs font-medium text-text-primary transition-colors disabled:opacity-50"
                : "rounded-full border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:bg-accent hover:border-border-strong hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            }
          >
            {PERFIL_FISICO_LABEL[slug]}
          </button>
        )
      })}
    </div>
  )
}
