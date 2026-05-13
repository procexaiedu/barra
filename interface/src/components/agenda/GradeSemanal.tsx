"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { dataBrt, dataInput } from "@/hooks/useAgenda"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioTipo, EstadoBloqueio } from "@/tipos/agenda"
import { deltaTempoIso } from "@/components/agenda/dnd"

const HORA_INICIO = 0
const HORA_FIM = 24
const HORA_HEIGHT = 80
const TOTAL_HORAS = HORA_FIM - HORA_INICIO
const TOTAL_HEIGHT = TOTAL_HORAS * HORA_HEIGHT
const GUTTER = 52
const SNAP_MIN = 15
const SNAP_PX = (SNAP_MIN / 60) * HORA_HEIGHT
const ALTURA_MINIMA_PX = (SNAP_MIN / 60) * HORA_HEIGHT

const diasSemana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

const estadoEstilo: Record<EstadoBloqueio, string> = {
  bloqueado: "border-l-[3px] border-l-sky-500 bg-sky-500/10",
  em_atendimento: "border-l-[3px] border-l-emerald-500 bg-emerald-500/10",
  concluido: "border-l-[3px] border-l-zinc-500 bg-zinc-500/10",
  cancelado: "border-l-[3px] border-l-zinc-500/40 bg-zinc-500/5 opacity-50",
}

const dotEstilo: Partial<Record<EstadoBloqueio, string>> = {
  bloqueado: "bg-sky-500",
  em_atendimento: "bg-emerald-500",
  concluido: "bg-zinc-500/50",
}

function horaMinBrt(iso: string): { h: number; m: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso))
  return {
    h: parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10),
    m: parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10),
  }
}

function horaParaY(iso: string): number {
  const { h, m } = horaMinBrt(iso)
  return Math.max(0, (h - HORA_INICIO + m / 60) * HORA_HEIGHT)
}

function alturaEvento(inicioIso: string, fimIso: string): number {
  const { h: h1, m: m1 } = horaMinBrt(inicioIso)
  const fim = horaMinBrt(fimIso)
  const m2 = fim.m
  // fim meia-noite BRT do dia seguinte → trata como 24:00
  const h2 = dataBrt(fimIso) > dataBrt(inicioIso) && fim.h === 0 && m2 === 0 ? 24 : fim.h
  return Math.max(((h2 + m2 / 60) - (h1 + m1 / 60)) * HORA_HEIGHT, 20)
}

function layoutDia(bloqueios: BloqueioTipo[]): Map<string, { col: number; totalCols: number }> {
  const sorted = [...bloqueios].sort((a, b) => a.inicio.localeCompare(b.inicio))
  const result = new Map<string, { col: number; totalCols: number }>()
  const grupos: BloqueioTipo[][] = []
  for (const ev of sorted) {
    const idx = grupos.findIndex((g) => g.some((e) => e.inicio < ev.fim && ev.inicio < e.fim))
    if (idx >= 0) grupos[idx].push(ev)
    else grupos.push([ev])
  }
  for (const grupo of grupos) {
    grupo.forEach((ev, i) => result.set(ev.id, { col: i, totalCols: grupo.length }))
  }
  return result
}

function CardGrade({
  bloqueio,
  altura,
  onClick,
  onResize,
  onResizeCommit,
  fimPreview,
  isDragging,
}: {
  bloqueio: BloqueioTipo
  altura: number
  onClick: () => void
  onResize: (novoFimIso: string) => void
  onResizeCommit: (novoFimIso: string) => void
  fimPreview: string | null
  isDragging: boolean
}) {
  const titulo = bloqueio.atendimento?.cliente_nome ?? bloqueio.observacao ?? null
  const nomeModelo = bloqueio.modelo_nome?.split(" ")[0]
  const numCurto = bloqueio.atendimento?.numero_curto
  const isEmAtendimento = bloqueio.estado === "em_atendimento"
  const dragDisabled = bloqueio.estado === "concluido" || bloqueio.estado === "cancelado"

  const { attributes, listeners, setNodeRef } = useDraggable({
    id: bloqueio.id,
    data: { bloqueio },
    disabled: dragDisabled,
  })

  const [resizing, setResizing] = useState(false)
  const resizeRef = useRef<{
    inicioPxY: number
    alturaInicial: number
    ultimoFimIso: string
  } | null>(null)

  const handleResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (dragDisabled) return
      e.stopPropagation()
      e.preventDefault()
      const startY = e.clientY
      resizeRef.current = {
        inicioPxY: startY,
        alturaInicial: altura,
        ultimoFimIso: bloqueio.fim,
      }
      setResizing(true)

      const handleMove = (ev: PointerEvent) => {
        if (!resizeRef.current) return
        const deltaY = ev.clientY - resizeRef.current.inicioPxY
        const novaAlturaRaw = resizeRef.current.alturaInicial + deltaY
        const snapped = Math.max(
          ALTURA_MINIMA_PX,
          Math.round(novaAlturaRaw / SNAP_PX) * SNAP_PX,
        )
        const deltaSnap = snapped - resizeRef.current.alturaInicial
        const novoFimIso = deltaTempoIso(bloqueio.fim, deltaSnap, HORA_HEIGHT, SNAP_MIN)
        resizeRef.current.ultimoFimIso = novoFimIso
        onResize(novoFimIso)
      }
      const handleUp = () => {
        const ultimoFim = resizeRef.current?.ultimoFimIso ?? bloqueio.fim
        resizeRef.current = null
        setResizing(false)
        window.removeEventListener("pointermove", handleMove)
        window.removeEventListener("pointerup", handleUp)
        window.removeEventListener("pointercancel", handleUp)
        onResizeCommit(ultimoFim)
      }
      window.addEventListener("pointermove", handleMove)
      window.addEventListener("pointerup", handleUp, { once: true })
      window.addEventListener("pointercancel", handleUp, { once: true })
    },
    [altura, bloqueio.fim, dragDisabled, onResize, onResizeCommit],
  )

  const fimLabel = fimPreview ?? bloqueio.fim
  const podeMostrarHandle = altura >= 24 && !dragDisabled

  return (
    <div
      ref={setNodeRef}
      data-slot="card-grade"
      className={cn(
        "relative h-full w-full",
        isDragging && "opacity-40",
        !dragDisabled && "cursor-grab active:cursor-grabbing",
      )}
      {...(dragDisabled ? {} : attributes)}
      {...(dragDisabled ? {} : listeners)}
    >
      <button
        type="button"
        onClick={onClick}
        onDoubleClick={(e) => e.stopPropagation()}
        className={cn(
          "h-full w-full overflow-hidden rounded text-left px-1.5 py-0.5 transition-[filter] hover:brightness-110",
          estadoEstilo[bloqueio.estado],
        )}
      >
        <div className="flex min-w-0 items-center gap-1">
          {isEmAtendimento && (
            <span className="inline-block h-1.5 w-1.5 flex-shrink-0 animate-pulse rounded-full bg-emerald-500" />
          )}
          <p className="truncate text-[10px] font-semibold leading-tight text-text-primary">
            {formatHorario(bloqueio.inicio)}–{formatHorario(fimLabel)}
            {nomeModelo && <span className="font-normal text-text-secondary"> · {nomeModelo}</span>}
            {numCurto && <span className="font-mono text-text-muted"> #{numCurto}</span>}
          </p>
        </div>
        {altura >= 48 && titulo && (
          <p className="mt-0.5 truncate text-[10px] leading-tight text-text-secondary">{titulo}</p>
        )}
      </button>
      {podeMostrarHandle && (
        <div
          data-resize-handle
          onPointerDown={handleResizePointerDown}
          className={cn(
            "absolute inset-x-0 bottom-0 h-1.5 cursor-ns-resize",
            resizing && "bg-ring/40",
          )}
        />
      )}
    </div>
  )
}

function LinhaHoraAtual({ diaIndex, totalDias }: { diaIndex: number; totalDias: number }) {
  const calcTop = () => {
    const { h, m } = horaMinBrt(new Date().toISOString())
    if (h < HORA_INICIO || h >= HORA_FIM) return null
    return (h - HORA_INICIO + m / 60) * HORA_HEIGHT
  }

  const [top, setTop] = useState<number | null>(calcTop)

  useEffect(() => {
    const id = setInterval(() => setTop(calcTop()), 60_000)
    return () => clearInterval(id)
  }, [])

  if (top === null) return null

  const colW = 100 / totalDias
  return (
    <div
      className="pointer-events-none absolute z-20 flex items-center"
      style={{ top: top - 1, left: `${diaIndex * colW}%`, width: `${colW}%` }}
    >
      <div className="-ml-1.5 h-3 w-3 flex-shrink-0 rounded-full bg-red-500" />
      <div className="h-0.5 flex-1 bg-red-500" />
    </div>
  )
}

function DiaColuna({
  data,
  isHoje,
  isFirst,
  bloqueios,
  onCriar,
  onEditar,
  onResize,
  onResizeCommit,
  fimPreviewPorId,
  draggingId,
}: {
  data: string
  isHoje: boolean
  isFirst: boolean
  bloqueios: BloqueioTipo[]
  onCriar: (data: string, inicio: string) => void
  onEditar: (b: BloqueioTipo) => void
  onResize: (id: string, novoFimIso: string) => void
  onResizeCommit: (id: string, novoFimIso: string) => void
  fimPreviewPorId: Map<string, string>
  draggingId: string | null
}) {
  const layout = useMemo(() => layoutDia(bloqueios), [bloqueios])
  const { setNodeRef, isOver } = useDroppable({ id: data })

  const handleDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    const y = e.clientY - rect.top
    const horaDecimal = HORA_INICIO + y / HORA_HEIGHT
    const hora = Math.min(Math.floor(horaDecimal), HORA_FIM - 1)
    const minutos = horaDecimal - Math.floor(horaDecimal) >= 0.5 ? 30 : 0
    onCriar(data, `${String(hora).padStart(2, "0")}:${String(minutos).padStart(2, "0")}`)
  }

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "relative border-l border-border/40",
        isFirst && "border-l-0",
        isHoje && "bg-primary/[0.03]",
        isOver && "ring-2 ring-ring/40 ring-inset",
      )}
      onDoubleClick={handleDoubleClick}
    >
      {bloqueios.map((b) => {
        const l = layout.get(b.id)!
        const top = horaParaY(b.inicio)
        const fimPreview = fimPreviewPorId.get(b.id) ?? null
        const fimEfetivo = fimPreview ?? b.fim
        const altura = Math.min(alturaEvento(b.inicio, fimEfetivo), TOTAL_HEIGHT - top)
        const colW = 100 / l.totalCols
        return (
          <div
            key={b.id}
            className="absolute px-[1px]"
            style={{
              top,
              height: altura,
              left: `${l.col * colW}%`,
              width: `${colW - 0.5}%`,
            }}
          >
            <CardGrade
              bloqueio={b}
              altura={altura}
              onClick={() => onEditar(b)}
              onResize={(novoFim) => onResize(b.id, novoFim)}
              onResizeCommit={(novoFim) => onResizeCommit(b.id, novoFim)}
              fimPreview={fimPreview}
              isDragging={draggingId === b.id}
            />
          </div>
        )
      })}
    </div>
  )
}

function DotsEvento({ bloqueiosDia }: { bloqueiosDia: BloqueioTipo[] }) {
  const relevantes = bloqueiosDia.filter((b) => b.estado !== "cancelado")
  if (relevantes.length === 0) return null
  const visiveis = relevantes.slice(0, 4)
  const extra = relevantes.length - visiveis.length
  return (
    <div className="flex items-center gap-0.5 pb-1">
      {visiveis.map((b) => {
        const cor = dotEstilo[b.estado]
        if (!cor) return null
        return (
          <span
            key={b.id}
            className={cn("h-1 w-1 flex-shrink-0 rounded-full", cor)}
          />
        )
      })}
      {extra > 0 && (
        <span className="text-[8px] leading-none text-text-muted">+{extra}</span>
      )}
    </div>
  )
}

export function GradeSemanal({
  dias,
  bloqueios,
  dataHoje,
  onCriar,
  onEditar,
  onMover,
}: {
  dias: Date[]
  bloqueios: BloqueioTipo[]
  dataHoje: string
  onCriar: (data: string, inicio: string) => void
  onEditar: (b: BloqueioTipo) => void
  onMover: (id: string, novoInicio: string, novoFim: string) => Promise<void>
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const diaHojeIndex = dias.findIndex((d) => dataInput(d) === dataHoje)
  const [draggingId, setDraggingId] = useState<string | null>(null)
  // Preview local durante resize; commit em pointerup chama onMover.
  const [fimPreviewPorId, setFimPreviewPorId] = useState<Map<string, string>>(new Map())

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const bloqueioPorId = useMemo(() => {
    const map = new Map<string, BloqueioTipo>()
    for (const b of bloqueios) map.set(b.id, b)
    return map
  }, [bloqueios])

  useEffect(() => {
    if (!scrollRef.current) return
    const now = new Date()
    const h = now.getHours()
    const targetHora = h >= HORA_INICIO && h < HORA_FIM ? Math.max(HORA_INICIO, h - 1) : HORA_INICIO
    scrollRef.current.scrollTop = (targetHora - HORA_INICIO) * HORA_HEIGHT
  }, [])

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setDraggingId(event.active.id as string)
  }, [])

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      setDraggingId(null)
      const { active, over, delta } = event
      if (!over) return

      const bloqueio = active.data.current?.bloqueio as BloqueioTipo | undefined
      if (!bloqueio) return

      const novaData = over.id as string
      const dataOriginal = dataBrt(bloqueio.inicio)

      // Calcula novo inicio: muda parte de data (se mudou de coluna) + delta vertical.
      const inicioComDelta = deltaTempoIso(bloqueio.inicio, delta.y, HORA_HEIGHT, SNAP_MIN)
      const fimComDelta = deltaTempoIso(bloqueio.fim, delta.y, HORA_HEIGHT, SNAP_MIN)

      let novoInicio = inicioComDelta
      let novoFim = fimComDelta
      if (novaData !== dataOriginal) {
        // Move dias inteiros preservando hora resultante do delta vertical.
        const diasDelta = diffDias(dataOriginal, novaData)
        const msDia = 24 * 60 * 60 * 1000
        novoInicio = new Date(new Date(inicioComDelta).getTime() + diasDelta * msDia).toISOString()
        novoFim = new Date(new Date(fimComDelta).getTime() + diasDelta * msDia).toISOString()
      }

      // No-op se nada mudou
      if (novoInicio === bloqueio.inicio && novoFim === bloqueio.fim) return

      await onMover(bloqueio.id, novoInicio, novoFim)
    },
    [onMover],
  )

  const handleResize = useCallback((id: string, novoFimIso: string) => {
    setFimPreviewPorId((m) => {
      const next = new Map(m)
      next.set(id, novoFimIso)
      return next
    })
  }, [])

  const handleResizeCommit = useCallback(
    (id: string, novoFimIso: string) => {
      setFimPreviewPorId((m) => {
        if (!m.has(id)) return m
        const next = new Map(m)
        next.delete(id)
        return next
      })
      const b = bloqueioPorId.get(id)
      if (!b) return
      if (novoFimIso === b.fim) return
      void onMover(id, b.inicio, novoFimIso)
    },
    [bloqueioPorId, onMover],
  )

  const bloqueioArrastando = draggingId ? bloqueioPorId.get(draggingId) : null

  return (
    <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      <section aria-label="Grade de horários" className="overflow-hidden rounded-lg border border-border bg-card">
        {/* Header: nomes dos dias + datas */}
        <div
          className="grid border-b border-border bg-card"
          style={{ gridTemplateColumns: `${GUTTER}px repeat(${dias.length}, 1fr)` }}
        >
          <div />
          {dias.map((dia) => {
            const data = dataInput(dia)
            const isHoje = data === dataHoje
            const diaSemIdx = (dia.getDay() + 6) % 7
            const bloqueiosDia = bloqueios.filter((b) => dataBrt(b.inicio) === data)
            return (
              <div
                key={data}
                className="flex flex-col items-center gap-0.5 border-l border-border py-2 first:border-l-0"
              >
                <span
                  className={cn(
                    "text-[10px] font-medium uppercase tracking-wider",
                    isHoje ? "text-text-brand" : "text-text-muted",
                  )}
                >
                  {diasSemana[diaSemIdx]}
                </span>
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold",
                    isHoje ? "bg-text-brand text-white" : "text-text-primary",
                  )}
                >
                  {dia.getDate()}
                </span>
                <DotsEvento bloqueiosDia={bloqueiosDia} />
              </div>
            )
          })}
        </div>

        {/* Corpo com scroll */}
        <div ref={scrollRef} className="overflow-y-auto" style={{ height: "calc(100vh - 360px)", minHeight: "400px", overflowX: "hidden" }}>
          <div className="relative" style={{ height: TOTAL_HEIGHT }}>

            {/* Coluna de horários (gutter) */}
            <div className="absolute left-0 top-0 z-10 bg-card" style={{ width: GUTTER, height: TOTAL_HEIGHT }}>
              {Array.from({ length: TOTAL_HORAS + 1 }, (_, i) => (
                <div
                  key={i}
                  className="absolute right-2 text-[10px] leading-none text-text-muted"
                  style={{ top: i * HORA_HEIGHT - 4 }}
                >
                  {`${String(HORA_INICIO + i).padStart(2, "0")}:00`}
                </div>
              ))}
            </div>

            {/* Linhas de hora e meia-hora */}
            <div className="pointer-events-none absolute inset-y-0" style={{ left: GUTTER, right: 0 }}>
              {Array.from({ length: TOTAL_HORAS + 1 }, (_, i) => (
                <div
                  key={i}
                  className="absolute w-full border-t border-border/50"
                  style={{ top: i * HORA_HEIGHT }}
                />
              ))}
              {Array.from({ length: TOTAL_HORAS }, (_, i) => (
                <div
                  key={`h${i}`}
                  className="absolute w-full border-t border-border/20"
                  style={{ top: i * HORA_HEIGHT + HORA_HEIGHT / 2 }}
                />
              ))}
            </div>

            {/* Colunas de dias + linha da hora atual */}
            <div className="absolute inset-y-0" style={{ left: GUTTER, right: 0 }}>
              <div
                className="grid h-full"
                style={{ gridTemplateColumns: `repeat(${dias.length}, 1fr)` }}
              >
                {dias.map((dia, j) => {
                  const data = dataInput(dia)
                  return (
                    <DiaColuna
                      key={data}
                      data={data}
                      isHoje={data === dataHoje}
                      isFirst={j === 0}
                      bloqueios={bloqueios.filter((b) => dataBrt(b.inicio) === data)}
                      onCriar={onCriar}
                      onEditar={onEditar}
                      onResize={handleResize}
                      onResizeCommit={handleResizeCommit}
                      fimPreviewPorId={fimPreviewPorId}
                      draggingId={draggingId}
                    />
                  )
                })}
              </div>
              {diaHojeIndex >= 0 && (
                <LinhaHoraAtual diaIndex={diaHojeIndex} totalDias={dias.length} />
              )}
            </div>
          </div>
        </div>
      </section>
      <DragOverlay>
        {bloqueioArrastando ? (
          <div className={cn("rounded px-1.5 py-0.5 shadow-md", estadoEstilo[bloqueioArrastando.estado])}>
            <p className="truncate text-[10px] font-semibold leading-tight text-text-primary">
              {formatHorario(bloqueioArrastando.inicio)}–{formatHorario(bloqueioArrastando.fim)}
            </p>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}

function diffDias(de: string, para: string): number {
  // Strings YYYY-MM-DD em BRT — diff em dias inteiros.
  const a = new Date(`${de}T12:00:00-03:00`).getTime()
  const b = new Date(`${para}T12:00:00-03:00`).getTime()
  return Math.round((b - a) / (24 * 60 * 60 * 1000))
}
