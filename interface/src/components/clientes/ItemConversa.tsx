"use client"

import { useState } from "react"
import type { KeyboardEvent } from "react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { ConversaListaItem, EstadoAtendimento, FiltroOrdem } from "@/tipos/clientes"
import { estadoAtendimentoLabel, motivoPerdaLabel } from "@/components/clientes/utils"

const ESTADOS_ATIVOS = new Set<EstadoAtendimento>([
  "Novo", "Triagem", "Qualificado", "Aguardando_confirmacao", "Confirmado", "Em_execucao",
])

export function ItemConversa({
  item,
  selected,
  ordenarPor,
  onSelect,
}: {
  item: ConversaListaItem
  selected: boolean
  ordenarPor: FiltroOrdem
  onSelect: (id: string) => void
}) {
  const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
  const refTempo = item.ultima_mensagem_em ?? item.created_at
  const ultimo = item.ultimo_atendimento

  const [agora] = useState(() => Date.now())
  const diasSemFechar = item.ultimo_fechamento_em
    ? Math.floor((agora - new Date(item.ultimo_fechamento_em).getTime()) / 86_400_000)
    : null
  const ultimoAtivo = ultimo ? ESTADOS_ATIVOS.has(ultimo.estado) : false
  const mostrarInatividade =
    diasSemFechar !== null && diasSemFechar >= 30 && !item.tem_atendimento_aberto && !ultimoAtivo
  const mostrarNuncaFechou = item.ultimo_fechamento_em === null && ordenarPor === "inatividade"

  const linhaModelo = [
    `Modelo: ${item.modelo.nome}`,
    ultimo ? `#${ultimo.numero_curto}` : null,
    item.ultimo_motivo_perda
      ? `perda: ${motivoPerdaLabel[item.ultimo_motivo_perda].toLowerCase()}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ")

  const border = selected
    ? "border-l-state-active"
    : item.tem_atendimento_aberto
      ? "border-l-state-handoff"
      : "border-l-transparent"

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onSelect(item.id)
    }
  }

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => onSelect(item.id)}
      onKeyDown={handleKeyDown}
      className={cn(
        "cursor-pointer border-l-3 bg-card px-4 py-2.5 transition-colors hover:bg-ink-200",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        selected ? "bg-ink-200" : "",
        border
      )}
    >
      <div className="flex items-baseline gap-2">
        <p className="truncate text-base font-semibold">
          <span className="font-semibold text-text-muted">Cliente:</span>{" "}
          <span className="text-text-primary">{cliente}</span>
        </p>
        <span className="ml-auto shrink-0 text-xs text-text-muted">
          {formatTempoRelativo(refTempo)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        {item.recorrente && (
          <Badge variant="paused" className="shrink-0">Recorrente</Badge>
        )}
        {mostrarInatividade && (
          <span className="shrink-0 text-xs text-amber-400">há {diasSemFechar}d sem fechar</span>
        )}
        {mostrarNuncaFechou && (
          <span className="shrink-0 text-xs text-text-muted">nunca fechou</span>
        )}
        {linhaModelo && (
          <p className="truncate text-xs text-text-muted">{linhaModelo}</p>
        )}
        {ultimo && (
          <span className="ml-auto shrink-0 text-xs text-text-muted">
            {estadoAtendimentoLabel[ultimo.estado]}
          </span>
        )}
      </div>
    </article>
  )
}
