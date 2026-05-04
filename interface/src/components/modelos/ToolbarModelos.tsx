"use client"

import { Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import type { FiltrosModelos } from "@/tipos/modelos"

export function ToolbarModelos({
  filtros,
  onChange,
}: {
  filtros: FiltrosModelos
  onChange: (filtros: FiltrosModelos) => void
}) {
  return (
    <section aria-label="Filtros de modelos" className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-72 flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" size={14} strokeWidth={1.5} />
        <Input
          value={filtros.busca}
          onChange={(event) => onChange({ ...filtros, busca: event.target.value })}
          placeholder="Buscar nome, número ou bairro"
          className="h-9 bg-input pl-9"
        />
      </div>
      <SelectFiltro
        label="Situação"
        value={filtros.status}
        onChange={(status) => onChange({ ...filtros, status: status as FiltrosModelos["status"] })}
        options={[
          ["todos", "Todas situações"],
          ["ativa", "Ativas"],
          ["pausada", "Pausadas"],
          ["inativa", "Inativas"],
        ]}
      />
      <SelectFiltro
        label="WhatsApp"
        value={filtros.evolution}
        onChange={(evolution) => onChange({ ...filtros, evolution: evolution as FiltrosModelos["evolution"] })}
        options={[
          ["todos", "Todos WhatsApp"],
          ["pareada", "WhatsApp pronto"],
          ["nao_pareada", "WhatsApp pendente"],
        ]}
      />
      <SelectFiltro
        label="Atende em"
        value={filtros.tipo}
        onChange={(tipo) => onChange({ ...filtros, tipo: tipo as FiltrosModelos["tipo"] })}
        options={[
          ["todos", "Atende em qualquer"],
          ["interno", "Atende no local dela"],
          ["externo", "Atende no local do cliente"],
        ]}
      />
    </section>
  )
}

function SelectFiltro({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (value: string) => void
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-9 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {options.map(([optionValue, optionLabel]) => (
        <option key={optionValue} value={optionValue}>
          {optionLabel}
        </option>
      ))}
    </select>
  )
}
