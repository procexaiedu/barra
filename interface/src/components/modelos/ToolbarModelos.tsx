"use client"

import { BuscaFiltro } from "@/components/filtros/BuscaFiltro"
import { SelectFiltro } from "@/components/filtros/SelectFiltro"
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
      <BuscaFiltro
        value={filtros.busca}
        onChange={(busca) => onChange({ ...filtros, busca })}
        placeholder="Buscar nome, número ou bairro"
        className="min-w-72 flex-1"
      />
      <SelectFiltro
        label="Situação"
        value={filtros.status}
        onChange={(status) => onChange({ ...filtros, status: status as FiltrosModelos["status"] })}
      >
        <option value="todos">Todas situações</option>
        <option value="ativa">Ativas</option>
        <option value="pausada">Pausadas</option>
        <option value="inativa">Inativas</option>
      </SelectFiltro>
      <SelectFiltro
        label="WhatsApp"
        value={filtros.evolution}
        onChange={(evolution) => onChange({ ...filtros, evolution: evolution as FiltrosModelos["evolution"] })}
      >
        <option value="todos">Todos WhatsApp</option>
        <option value="pareada">WhatsApp pronto</option>
        <option value="nao_pareada">WhatsApp pendente</option>
      </SelectFiltro>
      <SelectFiltro
        label="Atende em"
        value={filtros.tipo}
        onChange={(tipo) => onChange({ ...filtros, tipo: tipo as FiltrosModelos["tipo"] })}
      >
        <option value="todos">Atende em qualquer</option>
        <option value="interno">Atende no local dela</option>
        <option value="externo">Atende no local do cliente</option>
        <option value="remoto">Faz vídeo chamada</option>
      </SelectFiltro>
      <SelectFiltro
        label="Nível"
        value={filtros.nivel}
        onChange={(nivel) => onChange({ ...filtros, nivel: nivel as FiltrosModelos["nivel"] })}
      >
        <option value="todos">Todos níveis</option>
        <option value="A">Nível A</option>
        <option value="B">Nível B</option>
        <option value="C">Nível C</option>
        <option value="sem_nivel">Sem classificação</option>
      </SelectFiltro>
    </section>
  )
}
