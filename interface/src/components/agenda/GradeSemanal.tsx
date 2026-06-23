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
  type DragMoveEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { AlertTriangle, CalendarPlus } from "lucide-react"
import { dataBrt, dataInput } from "@/hooks/useAgenda"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioTipo } from "@/tipos/agenda"
import { calcularDestino, deltaTempoIso, horarioDeIso } from "@/components/agenda/dnd"
import { dotEstado, estiloCardCompleto } from "@/components/agenda/cores"

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
          estiloCardCompleto(bloqueio),
        )}
      >
        <div className="flex min-w-0 items-center gap-1">
          {isEmAtendimento && (
            <span className="inline-block size-1.5 flex-shrink-0 rounded-full bg-success-500 motion-safe:animate-pulse" />
          )}
          <p className="truncate text-[11px] font-semibold leading-tight text-text-primary">
            <span className="font-mono tabular-nums">{formatHorario(bloqueio.inicio)}–{formatHorario(fimLabel)}</span>
            {nomeModelo && <span className="font-normal text-text-secondary"> · {nomeModelo}</span>}
            {numCurto && <span className="font-mono text-text-muted"> #{numCurto}</span>}
          </p>
        </div>
        {altura >= 48 && titulo && (
          <p className="mt-0.5 truncate text-[11px] font-medium leading-tight text-text-secondary">{titulo}</p>
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
      <div className="-ml-1.5 size-3 flex-shrink-0 rounded-full bg-text-brand ring-2 ring-card" />
      <div className="h-0.5 flex-1 bg-text-brand" />
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

  // Guia visual do slot-alvo durante drag (Y snapped por SNAP_PX).
  // Usa ref para evitar setState em todo pointermove — só atualiza em mudança de slot.
  const [slotAlvoY, setSlotAlvoY] = useState<number | null>(null)
  const ultimoSlotRef = useRef<number | null>(null)

  const handlePointerMoveOver = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!isOver || draggingId === null) return
      const rect = e.currentTarget.getBoundingClientRect()
      const y = e.clientY - rect.top
      const snapped = Math.round(y / SNAP_PX) * SNAP_PX
      const clamped = Math.max(0, Math.min(TOTAL_HEIGHT - SNAP_PX, snapped))
      if (ultimoSlotRef.current !== clamped) {
        ultimoSlotRef.current = clamped
        setSlotAlvoY(clamped)
      }
    },
    [draggingId, isOver],
  )

  // Limpa guia quando o drag sai da coluna ou termina.
  useEffect(() => {
    if (!isOver || draggingId === null) {
      if (ultimoSlotRef.current !== null || slotAlvoY !== null) {
        ultimoSlotRef.current = null
        setSlotAlvoY(null)
      }
    }
  }, [draggingId, isOver, slotAlvoY])

  const slotHorarioLabel = useMemo(() => {
    if (slotAlvoY === null) return null
    const totalMin = (slotAlvoY / HORA_HEIGHT) * 60
    const h = Math.floor(totalMin / 60)
    const m = Math.round(totalMin - h * 60)
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
  }, [slotAlvoY])

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
      onPointerMove={handlePointerMoveOver}
    >
      {isOver && draggingId !== null && slotAlvoY !== null && (
        <>
          <div
            className="pointer-events-none absolute inset-x-0 h-px bg-ring/60"
            style={{ top: slotAlvoY }}
          />
          {slotHorarioLabel && (
            <span
              className="pointer-events-none absolute -left-12 text-[10px] font-medium tabular-nums text-text-brand"
              style={{ top: slotAlvoY - 5 }}
            >
              {slotHorarioLabel}
            </span>
          )}
        </>
      )}
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
        const cor = dotEstado(b)
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
  // Preview de horário em tempo real durante drag — atualizado em onDragMove.
  const [dragHorarioPreview, setDragHorarioPreview] = useState<{ inicio: string; fim: string } | null>(null)
  // Conflito detectado em tempo real durante drag — mostrado no DragOverlay.
  // Anti-thrash via ref: setState só roda na transição (entra/sai/troca de conflitante).
  const [conflitoAtivo, setConflitoAtivo] = useState<{ id: string; titulo: string } | null>(null)
  const ultimoConflitoRef = useRef<string | null>(null)

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
    ultimoConflitoRef.current = null
    setConflitoAtivo(null)
    const bloqueio = event.active.data.current?.bloqueio as BloqueioTipo | undefined
    if (bloqueio) {
      setDragHorarioPreview({
        inicio: horarioDeIso(bloqueio.inicio),
        fim: horarioDeIso(bloqueio.fim),
      })
    }
  }, [])

  const handleDragMove = useCallback((event: DragMoveEvent) => {
    const bloqueio = event.active.data.current?.bloqueio as BloqueioTipo | undefined
    if (!bloqueio) return
    const novoInicioIso = deltaTempoIso(bloqueio.inicio, event.delta.y, HORA_HEIGHT, SNAP_MIN)
    const novoFimIso = deltaTempoIso(bloqueio.fim, event.delta.y, HORA_HEIGHT, SNAP_MIN)
    setDragHorarioPreview({
      inicio: horarioDeIso(novoInicioIso),
      fim: horarioDeIso(novoFimIso),
    })
  }, [])

  // NB: `bloqueios` aqui já vem filtrado pelo tipo_atendimento do AgendaClient.
  // Se o filtro estiver ativo, conflitos em bloqueios filtrados-fora não aparecem
  // visualmente — servidor ainda recusa via 409 (toast trata).
  const handleDragOver = useCallback((event: DragOverEvent) => {
    const bloqueio = event.active.data.current?.bloqueio as BloqueioTipo | undefined
    if (!bloqueio || !event.over) {
      if (ultimoConflitoRef.current !== null) {
        ultimoConflitoRef.current = null
        setConflitoAtivo(null)
      }
      return
    }
    const dataOriginal = dataBrt(bloqueio.inicio)
    const { inicioIso, fimIso } = calcularDestino(
      bloqueio,
      event.delta.y,
      event.over.id as string,
      dataOriginal,
      HORA_HEIGHT,
      SNAP_MIN,
    )
    const conflitante = bloqueios.find(
      (b) =>
        b.id !== bloqueio.id &&
        b.estado !== "cancelado" &&
        b.inicio < fimIso &&
        inicioIso < b.fim,
    )
    const chave = conflitante?.id ?? ""
    if (ultimoConflitoRef.current === chave) return
    ultimoConflitoRef.current = chave
    setConflitoAtivo(
      conflitante
        ? {
            id: conflitante.id,
            titulo:
              conflitante.atendimento?.cliente_nome ??
              conflitante.observacao ??
              conflitante.modelo_nome?.split(" ")[0] ??
              "outro bloqueio",
          }
        : null,
    )
  }, [bloqueios])

  // Soft-warn: drop continua acionando onMover mesmo sob conflito visual.
  // Servidor (AgendaClient.moverBloqueio) é a única autoridade: retorna 409 e
  // refetch faz rollback. Bloquear no cliente arrisca falso-positivo (filtro
  // ativo, race com realtime, cancelados/concluídos).
  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      setDraggingId(null)
      setDragHorarioPreview(null)
      ultimoConflitoRef.current = null
      setConflitoAtivo(null)
      const { active, over, delta } = event
      if (!over) return

      const bloqueio = active.data.current?.bloqueio as BloqueioTipo | undefined
      if (!bloqueio) return

      const dataOriginal = dataBrt(bloqueio.inicio)
      const { inicioIso: novoInicio, fimIso: novoFim } = calcularDestino(
        bloqueio,
        delta.y,
        over.id as string,
        dataOriginal,
        HORA_HEIGHT,
        SNAP_MIN,
      )

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
  const vazio = bloqueios.length === 0

  // Cursor-grabbing global durante drag — flagado no body para sobrepor
  // qualquer cursor de hover de elementos sob o overlay.
  useEffect(() => {
    if (draggingId !== null) {
      document.body.classList.add("cursor-grabbing")
      return () => {
        document.body.classList.remove("cursor-grabbing")
      }
    }
  }, [draggingId])

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragMove={handleDragMove}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      autoScroll={{ threshold: { y: 0.15, x: 0 }, acceleration: 8 }}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Movendo bloqueio ${active.id}`,
          onDragOver: ({ over }) => {
            if (!over) return undefined
            return ultimoConflitoRef.current
              ? `Conflito detectado em ${over.id}`
              : `Sobre ${over.id}`
          },
          onDragEnd: ({ active, over }) =>
            over ? `Bloqueio ${active.id} solto em ${over.id}` : "Movimento cancelado",
          onDragCancel: ({ active }) => `Movimento de ${active.id} cancelado`,
        },
      }}
    >
      <section aria-label="Grade de horários" className="relative overflow-hidden rounded-lg border border-border bg-card shadow-elev-1 ring-1 ring-border-subtle">
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
                    "text-[11px] font-medium uppercase tracking-wider",
                    isHoje ? "text-text-brand" : "text-text-muted",
                  )}
                >
                  {diasSemana[diaSemIdx]}
                </span>
                <span
                  className={cn(
                    "flex size-7 items-center justify-center rounded-full text-sm font-semibold tabular-nums",
                    isHoje ? "bg-text-brand text-background" : "text-text-primary",
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
        <div ref={scrollRef} className="scroll-thin overflow-y-auto" style={{ height: "calc(100vh - 360px)", minHeight: "400px", overflowX: "hidden" }}>
          <div className="relative" style={{ height: TOTAL_HEIGHT }}>

            {/* Coluna de horários (gutter) */}
            <div className="absolute left-0 top-0 z-10 bg-card" style={{ width: GUTTER, height: TOTAL_HEIGHT }}>
              {Array.from({ length: TOTAL_HORAS + 1 }, (_, i) => (
                <div
                  key={i}
                  className="absolute right-2 font-mono text-[11px] leading-none tabular-nums text-text-muted"
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
                  className="absolute w-full border-t border-border/70"
                  style={{ top: i * HORA_HEIGHT }}
                />
              ))}
              {Array.from({ length: TOTAL_HORAS }, (_, i) => (
                <div
                  key={`h${i}`}
                  className="absolute w-full border-t border-border/30"
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
        {vazio && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
            <div className="flex max-w-xs flex-col items-center gap-2 text-center">
              <CalendarPlus size={28} strokeWidth={1.5} className="text-text-disabled" aria-hidden />
              <p className="text-sm font-medium text-text-secondary">Nenhum bloqueio neste período</p>
              <p className="text-xs leading-relaxed text-text-muted">
                Dê um duplo-clique num horário para criar um bloqueio ou agendamento.
              </p>
            </div>
          </div>
        )}
      </section>
      <DragOverlay>
        {bloqueioArrastando ? (
          <div
            data-slot="drag-overlay"
            className={cn(
              "rounded px-1.5 py-0.5 shadow-elev-3 transition-colors",
              estiloCardCompleto(bloqueioArrastando),
              conflitoAtivo && "motion-safe:animate-pulse ring-2 ring-danger-500 bg-danger-500/10",
            )}
          >
            <p className="truncate font-mono text-[11px] font-semibold leading-tight tabular-nums text-text-primary">
              {dragHorarioPreview
                ? `${dragHorarioPreview.inicio}–${dragHorarioPreview.fim}`
                : `${formatHorario(bloqueioArrastando.inicio)}–${formatHorario(bloqueioArrastando.fim)}`}
            </p>
            {conflitoAtivo && (
              <p className="mt-0.5 flex items-center gap-1 truncate text-[10px] leading-tight text-danger-500">
                <AlertTriangle className="h-3 w-3 flex-shrink-0" aria-hidden="true" />
                <span className="truncate">Conflito: {conflitoAtivo.titulo}</span>
              </p>
            )}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
