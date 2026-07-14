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
import { cn } from "@/lib/utils"
import { KanbanCard } from "@/components/atendimentos/KanbanCard"
import { corEstado } from "@/components/atendimentos/utils"
import { emitirContrato } from "@/lib/verify/contract"
import { useIsMobile } from "@/hooks/useMediaQuery"
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

// Próxima coluna ativa válida (avanço de exatamente uma etapa). Retorna null
// quando não há avanço ativo (item terminal ou já em Em_execucao — daí o
// avanço é para um terminal, tratado à parte). Mesma regra do drag desktop.
function proximaColunaAtiva(estado: EstadoAtendimento): Coluna | null {
  const origemId = estadoParaColunaId(estado)
  const origem = COLUNAS_ATIVAS.find((c) => c.id === origemId)
  if (!origem) return null
  return COLUNAS_ATIVAS.find((c) => c.indice === origem.indice + 1) ?? null
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
    <div className="flex min-w-[200px] flex-1 flex-col gap-2 2xl:min-w-[220px]">
      <div className="flex items-center justify-between px-1">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
          <span className={cn("h-1.5 w-1.5 rounded-full", corEstado(coluna.estados[0]).ponto)} aria-hidden />
          {coluna.titulo}
        </h3>
        <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-mono font-medium tabular-nums text-text-muted">{items.length}</span>
      </div>
      <div
        ref={setNodeRef}
        className={`flex min-h-[120px] flex-col gap-2 rounded-lg border p-2 ring-1 ring-border-subtle transition-colors ${classeRealce}`}
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
  const { listeners, setNodeRef, isDragging } = useDraggable({
    id: item.id,
    disabled: isTerminal,
    data: { item },
  })

  // O card inteiro é a alça de arraste (listeners no root). A constraint de 8px
  // do PointerSensor distingue clique-para-abrir de arraste, então não perdemos o
  // onClick. Terminais não arrastam.
  return (
    <KanbanCard
      ref={setNodeRef}
      item={item}
      onClick={() => onCardClick(item.id)}
      dragHandleProps={isTerminal ? undefined : { ...listeners }}
      arrastavel={!isTerminal}
      isDragging={false}
      style={{ opacity: isDragging ? 0.3 : 1 }}
    />
  )
}

// Ações de transição por toque no mobile (substitui o drag). Avanço de uma
// etapa ativa quando existe; em Em_execucao oferece os dois terminais.
function AcoesMobile({
  coluna,
  item,
  onAvancar,
  onSolicitarTerminal,
}: {
  coluna: Coluna
  item: AtendimentoListaItem
  onAvancar: (item: AtendimentoListaItem) => void
  onSolicitarTerminal: (item: AtendimentoListaItem, destino: "Fechado" | "Perdido") => void
}) {
  const proxAtiva = COLUNAS_ATIVAS.find((c) => c.indice === coluna.indice + 1)
  const botaoBase =
    "inline-flex h-9 flex-1 items-center justify-center gap-1 rounded-md border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"

  if (proxAtiva) {
    return (
      <button
        type="button"
        onClick={() => onAvancar(item)}
        className={cn(botaoBase, "border-border text-text-secondary hover:bg-accent hover:text-text-primary")}
      >
        Avançar para {proxAtiva.titulo} →
      </button>
    )
  }

  // Em_execucao: encerramento (abre o modal de valor/motivo).
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => onSolicitarTerminal(item, "Fechado")}
        className={cn(botaoBase, "border-success-500/50 text-success-600 hover:bg-success-500/10")}
      >
        Fechar
      </button>
      <button
        type="button"
        onClick={() => onSolicitarTerminal(item, "Perdido")}
        className={cn(botaoBase, "border-danger-500/50 text-danger-600 hover:bg-danger-500/10")}
      >
        Perder
      </button>
    </div>
  )
}

function ColunaMobile({
  coluna,
  items,
  onCardClick,
  onAvancar,
  onSolicitarTerminal,
}: {
  coluna: Coluna
  items: AtendimentoListaItem[]
  onCardClick: (id: string) => void
  onAvancar: (item: AtendimentoListaItem) => void
  onSolicitarTerminal: (item: AtendimentoListaItem, destino: "Fechado" | "Perdido") => void
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-1">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
          <span className={cn("h-1.5 w-1.5 rounded-full", corEstado(coluna.estados[0]).ponto)} aria-hidden />
          {coluna.titulo}
        </h3>
        <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-mono font-medium tabular-nums text-text-muted">{items.length}</span>
      </div>
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted p-2 ring-1 ring-border-subtle">
        {items.length === 0 && (
          <p className="px-2 py-4 text-center text-[11px] text-text-disabled">Nenhum atendimento</p>
        )}
        {items.map((item) => (
          <div key={item.id} className="flex flex-col gap-1.5">
            <KanbanCard item={item} onClick={() => onCardClick(item.id)} arrastavel={false} isDragging={false} />
            {!coluna.terminal && (
              <AcoesMobile
                coluna={coluna}
                item={item}
                onAvancar={onAvancar}
                onSolicitarTerminal={onSolicitarTerminal}
              />
            )}
          </div>
        ))}
      </div>
    </section>
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
  const isMobile = useIsMobile()
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

    // Só permite avançar exatamente uma coluna por vez: nunca regride e nunca pula
    // Aguardando (etapa de Pix / foto de portaria controlada pelo agente). O backend
    // reforça a mesma regra (409) caso a API seja chamada direto.
    if (colunaDestino.indice !== colunaOrigem.indice + 1) {
      toast.error(
        colunaDestino.indice <= colunaOrigem.indice
          ? "Não dá para voltar uma etapa do atendimento."
          : "Avance uma etapa por vez."
      )
      return
    }

    try {
      await onMoverEstado(item.id, colunaDestino.estadoDestino)
    } catch {
      toast.error("Erro ao mover atendimento")
    }
  }, [onMoverEstado, onSolicitarTerminal])

  // Avanço por toque (mobile): mesma regra de "uma etapa ativa por vez".
  const avancar = useCallback(
    async (item: AtendimentoListaItem) => {
      const prox = proximaColunaAtiva(item.estado)
      if (!prox) return
      try {
        await onMoverEstado(item.id, prox.estadoDestino)
      } catch {
        toast.error("Erro ao mover atendimento")
      }
    },
    [onMoverEstado]
  )

  const colunas = mostrarEncerrados ? [...COLUNAS_ATIVAS, ...COLUNAS_TERMINAIS] : COLUNAS_ATIVAS

  // Contrato de verificação: contagem por coluna (todas as 5, independente das visíveis)
  // + total. Invariante: Σ por coluna = items + encerrados (ninguém some no mapeamento).
  const contratoEstado = {
    total: items.length + itemsEncerrados.length,
    porColuna: Object.fromEntries(
      [...COLUNAS_ATIVAS, ...COLUNAS_TERMINAIS].map((c) => [c.id, (itensPorColuna.get(c.id) ?? []).length])
    ),
  }

  // Mobile: lista vertical por estado, transição por botões (sem DnD). O
  // contrato de verificação é emitido no mesmo container raiz das duas variantes.
  if (isMobile) {
    return (
      <div {...emitirContrato("kanban", contratoEstado)} className="flex h-full flex-col gap-3">
        <div className="flex-none flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onToggleEncerrados}
            className="text-[11px] font-medium text-text-muted underline-offset-2 hover:text-text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {mostrarEncerrados ? "Ocultar encerrados" : "Mostrar encerrados"}
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-2">
          {colunas.map((coluna) => (
            <ColunaMobile
              key={coluna.id}
              coluna={coluna}
              items={itensPorColuna.get(coluna.id) ?? []}
              onCardClick={onCardClick}
              onAvancar={avancar}
              onSolicitarTerminal={onSolicitarTerminal}
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <div {...emitirContrato("kanban", contratoEstado)} className="flex h-full flex-col gap-3">
        <div className="flex-none flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onToggleEncerrados}
            className="text-[11px] font-medium text-text-muted underline-offset-2 hover:text-text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
