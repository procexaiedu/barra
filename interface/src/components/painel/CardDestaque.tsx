"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { ClockAlert } from "lucide-react"
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
import type { CardDestaque as CardDestaqueType, IaPausadaMotivo } from "@/tipos/painel"

const BADGE_MAP: Record<IaPausadaMotivo, { variant: "revisao" | "handoff" | "paused"; label: string }> = {
  pix_em_revisao: { variant: "revisao", label: "Pix em revisão" },
  handoff_ia: { variant: "handoff", label: "Aguardando você" },
  modelo_em_atendimento: { variant: "paused", label: "Modelo em atendimento" },
}

const MOTIVO_LABEL: Record<IaPausadaMotivo, string> = {
  pix_em_revisao: "Pix duvidoso, precisa da sua decisão",
  handoff_ia: "IA escalou para você",
  modelo_em_atendimento: "Modelo passou do tempo previsto",
}

export function CardDestaque({ card }: { card: CardDestaqueType }) {
  const router = useRouter()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const badge = BADGE_MAP[card.ia_pausada_motivo]
  const nomeCliente = card.cliente_nome ?? card.cliente_telefone_formatado

  const handleCardClick = () => {
    router.push(`/atendimentos/${card.atendimento_id}`)
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

  return (
    <>
      <article
        role="link"
        tabIndex={0}
        onClick={handleCardClick}
        onKeyDown={handleCardKeyDown}
        className="cursor-pointer rounded-lg border-l-3 border-l-warn-500 bg-card p-6 transition-colors hover:bg-ink-200 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
      >
        <div className="flex items-center gap-3">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          {card.ia_pausada_motivo === "modelo_em_atendimento" && (
            <ClockAlert size={16} className="text-warn-500" />
          )}
          <span className="font-mono text-xs text-text-muted">#{card.numero_curto}</span>
          <span className="text-base font-semibold text-text-primary">{nomeCliente}</span>
        </div>

        <div className="mt-3 space-y-1">
          <div>
            <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
              MOTIVO{" "}
            </span>
            <span className="text-[13px] text-text-primary">
              {card.motivo_escalada ?? MOTIVO_LABEL[card.ia_pausada_motivo]}
            </span>
          </div>
          {card.proxima_acao_esperada && (
            <div>
              <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
                PRÓXIMA AÇÃO{" "}
              </span>
              <span className="text-[13px] text-text-muted">{card.proxima_acao_esperada}</span>
            </div>
          )}
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

        <div className="mt-3 border-t border-border pt-3">
          <p className="text-xs font-medium text-text-muted">
            Pausada {formatTempoRelativo(card.ia_pausada_em)} · Com {card.responsavel_atual === "IA" ? "IA" : card.responsavel_atual}
          </p>
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
