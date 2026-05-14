"use client"

import { useRouter } from "next/navigation"
import { Bot, User, Hand, ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { LinhaAgenda as LinhaAgendaType, EstadoBloqueio, OrigemBloqueio } from "@/tipos/painel"

const BADGE_MAP: Record<EstadoBloqueio, { variant: "paused" | "active" | "closed"; label: string }> = {
  bloqueado: { variant: "paused", label: "Agendado" },
  em_atendimento: { variant: "active", label: "Em atendimento" },
  concluido: { variant: "closed", label: "Concluído" },
  cancelado: { variant: "paused", label: "Cancelado" },
}

const ORIGEM_ICON: Record<OrigemBloqueio, { icon: typeof Bot; tooltip: string }> = {
  ia: { icon: Bot, tooltip: "IA" },
  painel_fernando: { icon: User, tooltip: "Fernando" },
  manual: { icon: Hand, tooltip: "Manual" },
}

export function LinhaAgenda({
  linha,
  mostrarModelo = false,
  onAbrirDetalhes,
}: {
  linha: LinhaAgendaType
  mostrarModelo?: boolean
  onAbrirDetalhes?: () => void
}) {
  const router = useRouter()
  const badge = BADGE_MAP[linha.estado]
  const origem = ORIGEM_ICON[linha.origem]
  const OrigemIcon = origem.icon
  const isCancelado = linha.estado === "cancelado"

  const handleClick = () => {
    if (onAbrirDetalhes) {
      onAbrirDetalhes()
      return
    }
    const data = linha.inicio.split("T")[0]
    router.push(`/agenda?data=${data}&bloqueio=${linha.id}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      handleClick()
    }
  }

  const nomeCliente = linha.atendimento_id
    ? (linha.cliente_nome ?? "Cliente")
    : (linha.observacao ?? "Bloqueio manual")

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        "flex h-14 cursor-pointer items-center gap-4 border-b border-border px-4 transition-colors hover:bg-accent",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        isCancelado && "line-through opacity-60"
      )}
    >
      <span className="min-w-[110px] font-mono text-xs text-text-primary">
        {formatHorario(linha.inicio)}–{formatHorario(linha.fim)}
      </span>
      <Badge variant={badge.variant}>{badge.label}</Badge>
      <span className="flex-1 truncate text-[13px] text-text-primary">{nomeCliente}</span>
      {mostrarModelo && (
        <span className="text-xs text-text-muted">{linha.modelo_nome}</span>
      )}
      <Tooltip>
        <TooltipTrigger render={<span />} className="inline-flex">
          <OrigemIcon size={16} strokeWidth={1.5} className="text-text-muted" />
        </TooltipTrigger>
        <TooltipContent>{origem.tooltip}</TooltipContent>
      </Tooltip>
      <ChevronRight size={16} className="text-text-muted" />
    </div>
  )
}
