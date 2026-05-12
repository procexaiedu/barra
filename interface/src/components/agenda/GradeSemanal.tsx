"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { dataBrt, dataInput } from "@/hooks/useAgenda"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioTipo, EstadoBloqueio } from "@/tipos/agenda"

const HORA_INICIO = 0
const HORA_FIM = 24
const HORA_HEIGHT = 80
const TOTAL_HORAS = HORA_FIM - HORA_INICIO
const TOTAL_HEIGHT = TOTAL_HORAS * HORA_HEIGHT
const GUTTER = 52

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
}: {
  bloqueio: BloqueioTipo
  altura: number
  onClick: () => void
}) {
  const titulo = bloqueio.atendimento?.cliente_nome ?? bloqueio.observacao ?? null
  const nomeModelo = bloqueio.modelo_nome?.split(" ")[0]
  const numCurto = bloqueio.atendimento?.numero_curto
  const isEmAtendimento = bloqueio.estado === "em_atendimento"

  return (
    <button
      type="button"
      onClick={onClick}
      onDoubleClick={(e) => e.stopPropagation()}
      className={cn(
        "h-full w-full overflow-hidden rounded text-left px-1.5 py-0.5 transition-[filter] hover:brightness-110",
        estadoEstilo[bloqueio.estado]
      )}
    >
      <div className="flex min-w-0 items-center gap-1">
        {isEmAtendimento && (
          <span className="inline-block h-1.5 w-1.5 flex-shrink-0 animate-pulse rounded-full bg-emerald-500" />
        )}
        <p className="truncate text-[10px] font-semibold leading-tight text-text-primary">
          {formatHorario(bloqueio.inicio)}–{formatHorario(bloqueio.fim)}
          {nomeModelo && <span className="font-normal text-text-secondary"> · {nomeModelo}</span>}
          {numCurto && <span className="font-mono text-text-muted"> #{numCurto}</span>}
        </p>
      </div>
      {altura >= 48 && titulo && (
        <p className="mt-0.5 truncate text-[10px] leading-tight text-text-secondary">{titulo}</p>
      )}
    </button>
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
}: {
  data: string
  isHoje: boolean
  isFirst: boolean
  bloqueios: BloqueioTipo[]
  onCriar: (data: string, inicio: string) => void
  onEditar: (b: BloqueioTipo) => void
}) {
  const layout = useMemo(() => layoutDia(bloqueios), [bloqueios])

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
      className={cn(
        "relative border-l border-border/40",
        isFirst && "border-l-0",
        isHoje && "bg-primary/[0.03]"
      )}
      onDoubleClick={handleDoubleClick}
    >
      {bloqueios.map((b) => {
        const l = layout.get(b.id)!
        const top = horaParaY(b.inicio)
        const altura = Math.min(alturaEvento(b.inicio, b.fim), TOTAL_HEIGHT - top)
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
            <CardGrade bloqueio={b} altura={altura} onClick={() => onEditar(b)} />
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
}: {
  dias: Date[]
  bloqueios: BloqueioTipo[]
  dataHoje: string
  onCriar: (data: string, inicio: string) => void
  onEditar: (b: BloqueioTipo) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const diaHojeIndex = dias.findIndex((d) => dataInput(d) === dataHoje)

  useEffect(() => {
    if (!scrollRef.current) return
    const now = new Date()
    const h = now.getHours()
    const targetHora = h >= HORA_INICIO && h < HORA_FIM ? Math.max(HORA_INICIO, h - 1) : HORA_INICIO
    scrollRef.current.scrollTop = (targetHora - HORA_INICIO) * HORA_HEIGHT
  }, [])

  return (
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
                  isHoje ? "text-text-brand" : "text-text-muted"
                )}
              >
                {diasSemana[diaSemIdx]}
              </span>
              <span
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold",
                  isHoje ? "bg-text-brand text-white" : "text-text-primary"
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
  )
}
