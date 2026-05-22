"use client"

import { useCallback, useMemo, useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  useDroppable,
  useDraggable,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { toast } from "sonner"
import { KanbanCard } from "@/components/atendimentos/KanbanCard"
import type { AtendimentoListaItem, EstadoAtendimento, EstadoKanbanDestino } from "@/tipos/atendimentos"

interface Coluna {
  id: string
  titulo: string
  estados: EstadoAtendimento[]
  estadoDestino: EstadoKanbanDestino
  indice: number
  terminal: boolean
}

const COLUNAS_ATIVAS: Coluna[] = [
  { id: "Qualificando", titulo: "Qualificando", estados: ["Novo", "Triagem", "Qualificado"], estadoDestino: "Qualificado", indice: 0, terminal: false },
  { id: "Aguardando", titulo: "Aguardando", estados: ["Aguardando_confirmacao", "Confirmado"], estadoDestino: "Aguardando_confirmacao", indice: 1, terminal: false },
  { id: "Em_execucao", titulo: "Em atendimento", estados: ["Em_execucao"], estadoDestino: "Em_execucao", indice: 2, terminal: false },
]

const COLUNAS_TERMINAIS: Coluna[] = [
  { id: "Fechado", titulo: "Fechado", estados: ["Fechado"], estadoDestino: "Qualificado", indice: 3, terminal: true },
  { id: "Perdido", titulo: "Perdido", estados: ["Perdido"], estadoDestino: "Qualificado", indice: 4, terminal: true },
]

function estadoParaColunaId(estado: EstadoAtendimento): string {
  for (const coluna of [...COLUNAS_ATIVAS, ...COLUNAS_TERMINAIS]) {
    if (coluna.estados.includes(estado)) return coluna.id
  }
  return "Qualificando"
}

function ColunaDroppable({
  coluna,
  items,
  onCardClick,
  dragAtivo,
}: {
  coluna: Coluna
  items: AtendimentoListaItem[]
  onCardClick: (id: string) => void
  dragAtivo: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: coluna.id })

  // Realce do alvo: terminais usam cor por estado (verde fechado / vermelho perdido);
  // colunas ativas mantêm o realce neutro.
  const terminalHighlight = coluna.id === "Fechado" ? "border-success-500/60 bg-success-500/10" : "border-danger-500/60 bg-danger-500/10"
  const classeRealce = coluna.terminal
    ? isOver
      ? terminalHighlight
      : dragAtivo
        ? coluna.id === "Fechado"
          ? "border-success-500/40 border-dashed bg-muted"
          : "border-danger-500/40 border-dashed bg-muted"
        : "border-border bg-muted"
    : isOver
      ? "border-ring/60 bg-accent"
      : "border-border bg-muted"

  return (
    <div className="flex min-w-[220px] flex-1 flex-col gap-2">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">{coluna.titulo}</h3>
        <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium text-text-muted">{items.length}</span>
      </div>
      <div
        ref={setNodeRef}
        className={`flex min-h-[120px] flex-col gap-2 rounded-lg border p-2 transition-colors ${classeRealce}`}
      >
        {items.map((item) => (
          <DraggableCard key={item.id} item={item} onCardClick={onCardClick} isTerminal={coluna.terminal} />
        ))}
        {items.length === 0 && (
          <p className="px-2 py-4 text-center text-[11px] text-text-disabled">Nenhum atendimento</p>
        )}
      </div>
    </div>
  )
}

function DraggableCard({
  item,
  onCardClick,
  isTerminal,
}: {
  item: AtendimentoListaItem
  onCardClick: (id: string) => void
  isTerminal: boolean
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: item.id,
    disabled: isTerminal,
    data: { item },
  })

  return (
    <div ref={setNodeRef} style={{ opacity: isDragging ? 0.3 : 1 }}>
      <KanbanCard
        item={item}
        onClick={() => onCardClick(item.id)}
        dragHandleProps={isTerminal ? {} : { ...attributes, ...listeners }}
        isDragging={false}
      />
    </div>
  )
}

export function KanbanBoard({
  items,
  itemsEncerrados,
  mostrarEncerrados,
  onToggleEncerrados,
  onCardClick,
  onMoverEstado,
  onSolicitarTerminal,
}: {
  items: AtendimentoListaItem[]
  itemsEncerrados: AtendimentoListaItem[]
  mostrarEncerrados: boolean
  onToggleEncerrados: () => void
  onCardClick: (id: string) => void
  onMoverEstado: (id: string, estado: EstadoKanbanDestino) => Promise<void>
  onSolicitarTerminal: (item: AtendimentoListaItem, destino: "Fechado" | "Perdido") => void
}) {
  const [draggingItem, setDraggingItem] = useState<AtendimentoListaItem | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const itensPorColuna = useMemo(() => {
    const mapa = new Map<string, AtendimentoListaItem[]>()
    for (const coluna of COLUNAS_ATIVAS) mapa.set(coluna.id, [])
    for (const coluna of COLUNAS_TERMINAIS) mapa.set(coluna.id, [])
    for (const item of items) {
      const colunaId = estadoParaColunaId(item.estado)
      mapa.get(colunaId)?.push(item)
    }
    for (const item of itemsEncerrados) {
      const colunaId = estadoParaColunaId(item.estado)
      mapa.get(colunaId)?.push(item)
    }
    return mapa
  }, [items, itemsEncerrados])

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const item = event.active.data.current?.item as AtendimentoListaItem | undefined
    setDraggingItem(item ?? null)
  }, [])

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    setDraggingItem(null)
    const { active, over } = event
    if (!over) return

    const item = active.data.current?.item as AtendimentoListaItem | undefined
    if (!item) return

    const origemId = estadoParaColunaId(item.estado)
    const destinoId = over.id as string

    if (origemId === destinoId) return

    // Destino terminal (Fechado/Perdido): não move direto — solicita modal de
    // valor_final / motivo. Cancelar no modal mantém o card no estado original.
    const colunaTerminal = COLUNAS_TERMINAIS.find((c) => c.id === destinoId)
    if (colunaTerminal) {
      onSolicitarTerminal(item, colunaTerminal.id as "Fechado" | "Perdido")
      return
    }

    const colunaOrigem = COLUNAS_ATIVAS.find((c) => c.id === origemId)
    const colunaDestino = COLUNAS_ATIVAS.find((c) => c.id === destinoId)
    if (!colunaOrigem || !colunaDestino) return

    // Só permite avanço entre colunas ativas
    if (colunaDestino.indice <= colunaOrigem.indice) return

    try {
      await onMoverEstado(item.id, colunaDestino.estadoDestino)
    } catch {
      toast.error("Erro ao mover atendimento")
    }
  }, [onMoverEstado, onSolicitarTerminal])

  const colunas = mostrarEncerrados ? [...COLUNAS_ATIVAS, ...COLUNAS_TERMINAIS] : COLUNAS_ATIVAS

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div className="flex h-full flex-col gap-3">
        <div className="flex-none flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onToggleEncerrados}
            className="text-[11px] font-medium text-text-muted underline-offset-2 hover:text-text-primary hover:underline focus-visible:outline-none"
          >
            {mostrarEncerrados ? "Ocultar encerrados" : "Mostrar encerrados"}
          </button>
        </div>
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto pb-2">
          {colunas.map((coluna) => (
            <ColunaDroppable
              key={coluna.id}
              coluna={coluna}
              items={itensPorColuna.get(coluna.id) ?? []}
              onCardClick={onCardClick}
              dragAtivo={draggingItem !== null}
            />
          ))}
        </div>
      </div>
      <DragOverlay>
        {draggingItem ? (
          <KanbanCard item={draggingItem} onClick={() => {}} isDragging />
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
