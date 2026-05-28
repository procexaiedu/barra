"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Clock, ScanSearch } from "lucide-react"
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

const BADGE_MAP: Record<IaPausadaMotivo, { variant: "revisao" | "handoff" | "info"; label: string; borderClass: string }> = {
  pix_em_revisao:        { variant: "revisao", label: "Pix em revisão",   borderClass: "border-l-danger-500" },
  handoff_ia:            { variant: "handoff", label: "Aguardando você",  borderClass: "border-l-warn-500"   },
  modelo_em_atendimento: { variant: "info",    label: "Modelo atendendo", borderClass: "border-l-info-500"   },
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
        className={cn("group cursor-pointer rounded-lg border-l-4 bg-card p-5 ring-1 ring-foreground/10 transition-colors hover:bg-surface-hover hover:ring-border-brand/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none", badge.borderClass, flashing && "tile-update-flash")}
      >
        <div className="flex items-center gap-2.5">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <span className={cn("ml-auto flex items-center gap-1 text-xs font-medium tabular-nums", urgenciaClasse(card.ia_pausada_em))}>
            <Clock size={12} strokeWidth={1.75} aria-hidden />
            {formatTempoRelativo(card.ia_pausada_em)}
          </span>
          {onAbrirContexto && (
            <button
              type="button"
              aria-label="Ver contexto e decidir"
              onClick={(e) => { e.stopPropagation(); onAbrirContexto() }}
              className="-mr-1 rounded p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <ScanSearch size={15} />
            </button>
          )}
        </div>

        <p className="mt-3 truncate text-base font-semibold text-text-primary">{nomeCliente}</p>
        {/* Motivo da escalada é o conteúdo principal do card (sem rótulo 'MOTIVO') */}
        <p className="mt-1 text-[13px] leading-snug text-text-secondary">
          {motivoExibido(card.motivo_escalada, card.ia_pausada_motivo)}
        </p>
        {/* Campo 'Próxima Ação' obsoleto no MVP (task 0855ee14) */}

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

        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
          <span className="text-xs font-medium text-text-muted">{card.modelo_nome} · #{card.numero_curto}</span>
          <span className="text-xs text-text-muted">Com {card.responsavel_atual === "IA" ? "IA" : card.responsavel_atual}</span>
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
