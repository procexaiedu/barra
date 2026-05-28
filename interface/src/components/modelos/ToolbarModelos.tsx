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
    <section aria-label="Filtros de modelos" className="flex flex-wrap items-end gap-2">
      <label className="relative flex min-w-72 flex-1 flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Buscar</span>
        <Search className="pointer-events-none absolute left-3 bottom-2.5 text-text-muted" size={14} strokeWidth={1.5} />
        <Input
          value={filtros.busca}
          onChange={(event) => onChange({ ...filtros, busca: event.target.value })}
          placeholder="Buscar nome, número ou bairro"
          className="h-9 bg-input pl-9"
        />
      </label>
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
      <SelectFiltro
        label="Nível"
        value={filtros.nivel}
        onChange={(nivel) => onChange({ ...filtros, nivel: nivel as FiltrosModelos["nivel"] })}
        options={[
          ["todos", "Todos níveis"],
          ["A", "Nível A"],
          ["B", "Nível B"],
          ["C", "Nível C"],
          ["sem_nivel", "Sem classificação"],
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
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      <select
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
    </label>
  )
}
