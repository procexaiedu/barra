"use client"

import { useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { GridMidia } from "@/components/modelos/GridMidia"
import type { MidiaItem, TipoMidia } from "@/tipos/modelos"

type FiltroAprovacao = "aprovadas" | "nao_aprovadas" | "todas"

export function AbaMidia({
  midia,
  onAdicionar,
  onOpen,
  onToggleAprovada,
  onDelete,
}: {
  midia: MidiaItem[]
  onAdicionar: () => void
  onOpen: (item: MidiaItem) => void
  onToggleAprovada: (item: MidiaItem) => void
  onDelete: (item: MidiaItem) => void
}) {
  const [tipo, setTipo] = useState<"todos" | TipoMidia>("todos")
  const [tag, setTag] = useState("todas")
  const [aprovacao, setAprovacao] = useState<FiltroAprovacao>("aprovadas")
  const tags = useMemo(() => Array.from(new Set(midia.map((item) => item.tag))).sort(), [midia])
  const items = useMemo(() => midia.filter((item) => {
    if (tipo !== "todos" && item.tipo !== tipo) return false
    if (tag !== "todas" && item.tag !== tag) return false
    if (aprovacao === "aprovadas" && !item.aprovada) return false
    if (aprovacao === "nao_aprovadas" && item.aprovada) return false
    return true
  }), [aprovacao, midia, tag, tipo])

  return (
    <div className="space-y-3">
      <section aria-label="Filtros de midia" className="flex flex-wrap items-center gap-2">
        <Select label="Tipo" value={tipo} onChange={(value) => setTipo(value as "todos" | TipoMidia)} options={[["todos", "Todos os tipos"], ["foto", "Fotos"], ["video", "Vídeos"]]} />
        <Select label="Tag" value={tag} onChange={setTag} options={[["todas", "Todas as tags"], ...tags.map((t): [string, string] => [t, t])]} />
        <Select label="Status" value={aprovacao} onChange={(value) => setAprovacao(value as FiltroAprovacao)} options={[["aprovadas", "Ativas"], ["nao_aprovadas", "Inativas"], ["todas", "Todas"]]} />
        <div className="ml-auto">
          <Button variant="primary" size="sm" onClick={onAdicionar}>Adicionar mídia</Button>
        </div>
      </section>
      <GridMidia items={items} onOpen={onOpen} onToggleAprovada={onToggleAprovada} onDelete={onDelete} />
    </div>
  )
}

function Select({
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
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)} className="h-9 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}
