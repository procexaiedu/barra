"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { AlertCircle, Clock, ClockAlert, ScanSearch, type LucideIcon } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { formatTempoRelativo } from "@/lib/formatters"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { motivoExibido } from "@/components/atendimentos/utils"
import type { CardDestaque as CardDestaqueType, IaPausadaMotivo } from "@/tipos/painel"

const BADGE_MAP: Record<IaPausadaMotivo, { variant: "revisao" | "handoff" | "paused"; label: string; borderClass: string; Icon: LucideIcon }> = {
  pix_em_revisao:        { variant: "revisao", label: "Pix em revisão",   borderClass: "border-l-danger-500", Icon: AlertCircle },
  handoff_ia:            { variant: "handoff", label: "Aguardando você",  borderClass: "border-l-warn-500",   Icon: Clock       },
  modelo_em_atendimento: { variant: "paused",  label: "Modelo atendendo", borderClass: "border-l-info-500",   Icon: ClockAlert  },
}

function urgenciaClasse(iaEmAt: string): string {
  const mins = (Date.now() - new Date(iaEmAt).getTime()) / 60_000
  if (mins > 120) return "text-danger-500"
  if (mins > 30) return "text-warn-500"
  return "text-text-muted"
}

export function CardDestaque({
  card,
  compacto = false,
  flashing = false,
  onAbrirContexto,
}: {
  card: CardDestaqueType
  compacto?: boolean
  flashing?: boolean
  onAbrirContexto?: () => void
}) {
  const router = useRouter()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const badge = BADGE_MAP[card.ia_pausada_motivo]
  const nomeCliente = card.cliente_nome ?? card.cliente_telefone_formatado

  const handleCardClick = () => {
    router.push(`/atendimentos?id=${card.atendimento_id}`)
  }

  const handleCardKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      handleCardClick()
    }
  }

  const handleDevolver = async () => {
    setLoading(true)
    try {
      await api(`/v1/atendimentos/${card.atendimento_id}/devolver`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      toast.success(`Atendimento #${card.numero_curto} devolvido para a IA`)
      setDialogOpen(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao devolver")
    } finally {
      setLoading(false)
    }
  }

  if (compacto) {
    return (
      <>
        <article
          role="link"
          tabIndex={0}
          onClick={handleCardClick}
          onKeyDown={handleCardKeyDown}
          className={cn(
            "flex cursor-pointer items-center gap-3 border-l-3 bg-card px-4 py-2.5",
            "transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            badge.borderClass,
          )}
        >
          <Badge variant={badge.variant} className="shrink-0">{badge.label}</Badge>
          <span className="min-w-0 truncate text-sm font-semibold text-text-primary">{nomeCliente}</span>
          {/* Campo 'Próxima Ação' obsoleto no MVP (task 0855ee14) */}
          <span className="shrink-0 text-xs text-text-muted">{card.modelo_nome} #{card.numero_curto}</span>
          {card.ia_pausada_motivo === "modelo_em_atendimento" && (
            <Button
              variant="default"
              size="sm"
              className="shrink-0"
              onClick={(e) => { e.stopPropagation(); setDialogOpen(true) }}
            >
              Devolver para IA
            </Button>
          )}
        </article>

        <AlertDialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <AlertDialogContent className="max-w-md bg-card">
            <AlertDialogHeader>
              <AlertDialogTitle className="text-lg font-semibold text-text-primary">
                Devolver #{card.numero_curto} para a IA?
              </AlertDialogTitle>
              <AlertDialogDescription className="text-sm text-text-secondary">
                A IA volta a responder o cliente na próxima mensagem.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={loading}>Cancelar</AlertDialogCancel>
              <AlertDialogAction onClick={handleDevolver} disabled={loading}>
                {loading ? "Devolvendo…" : "Confirmar devolução"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </>
    )
  }

  return (
    <>
      <article
        role="link"
        tabIndex={0}
        onClick={handleCardClick}
        onKeyDown={handleCardKeyDown}
        className={cn("cursor-pointer rounded-lg border-l-3 bg-card p-6 transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none", badge.borderClass, flashing && "tile-update-flash")}
      >
        <div className="flex items-center gap-3">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <badge.Icon size={14} className="shrink-0 text-text-muted" aria-hidden />
          <span className="text-base font-semibold text-text-primary">{nomeCliente}</span>
          {onAbrirContexto && (
            <button
              type="button"
              aria-label="Ver contexto e decidir"
              onClick={(e) => { e.stopPropagation(); onAbrirContexto() }}
              className="ml-auto rounded p-1 text-text-muted hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <ScanSearch size={15} />
            </button>
          )}
        </div>

        <div className="mt-3 space-y-1">
          <div>
            <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
              MOTIVO{" "}
            </span>
            <span className="text-[13px] text-text-primary">
              {motivoExibido(card.motivo_escalada, card.ia_pausada_motivo)}
            </span>
          </div>
          {/* Campo 'Próxima Ação' obsoleto no MVP (task 0855ee14) */}
        </div>

        {card.ia_pausada_motivo === "modelo_em_atendimento" && (
          <div className="mt-3">
            <Button
              variant="default"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                setDialogOpen(true)
              }}
            >
              Devolver para IA
            </Button>
          </div>
        )}

        <div className="mt-3 border-t border-border pt-3 flex items-center justify-between">
          <p className={cn("text-xs font-medium", urgenciaClasse(card.ia_pausada_em))}>
            Pausada {formatTempoRelativo(card.ia_pausada_em)} · Com {card.responsavel_atual === "IA" ? "IA" : card.responsavel_atual}
          </p>
          <span className="text-xs font-medium text-text-muted">{card.modelo_nome} #{card.numero_curto}</span>
        </div>
      </article>

      <AlertDialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Devolver #{card.numero_curto} para a IA?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A IA volta a responder o cliente na próxima mensagem.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={loading}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDevolver} disabled={loading}>
              {loading ? "Devolvendo…" : "Confirmar devolução"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
