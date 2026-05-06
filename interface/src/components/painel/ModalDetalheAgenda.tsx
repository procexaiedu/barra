"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { Bot, User, Hand, ExternalLink, X } from "lucide-react"
import { toast } from "sonner"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatHorario, formatData, formatDiaSemana } from "@/lib/formatters"
import type { LinhaAgenda, EstadoBloqueio, OrigemBloqueio } from "@/tipos/painel"

// ── helpers locais ────────────────────────────────────────────────────────────

const BADGE_MAP: Record<EstadoBloqueio, { variant: "paused" | "active" | "closed"; label: string }> = {
  bloqueado: { variant: "paused", label: "Agendado" },
  em_atendimento: { variant: "active", label: "Em atendimento" },
  concluido: { variant: "closed", label: "Concluído" },
  cancelado: { variant: "paused", label: "Cancelado" },
}

const ORIGEM_INFO: Record<OrigemBloqueio, { icon: typeof Bot; label: string }> = {
  ia: { icon: Bot, label: "Criado pela IA" },
  painel_fernando: { icon: User, label: "Criado por Fernando" },
  manual: { icon: Hand, label: "Manual" },
}

function formatDuracao(inicio: string, fim: string): string {
  const minutos = Math.round((new Date(fim).getTime() - new Date(inicio).getTime()) / 60_000)
  if (minutos < 60) return `${minutos}min`
  const h = Math.floor(minutos / 60)
  const m = minutos % 60
  return m === 0 ? `${h}h` : `${h}h${m}min`
}

function capitalizar(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// ── sub-componentes ───────────────────────────────────────────────────────────

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">{label} </span>
      <span className="text-[13px] text-text-primary">{value}</span>
    </div>
  )
}

// ── componente principal ──────────────────────────────────────────────────────

export function ModalDetalheAgenda({
  linha,
  onFechar,
  onBloqueioAlterado,
}: {
  linha: LinhaAgenda | null
  onFechar: () => void
  onBloqueioAlterado: () => void
}) {
  const [cancelando, setCancelando] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)

  useEffect(() => {
    if (!linha) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCancelando(false)
    setConfirmCancel(false)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linha?.id])

  async function handleCancelar() {
    if (!linha) return
    setCancelando(true)
    try {
      await api(`/v1/agenda/bloqueios/${linha.id}/cancelar`, {
        method: "POST",
        body: JSON.stringify({ confirmar: linha.estado === "em_atendimento" }),
      })
      toast.success("Bloqueio cancelado")
      onBloqueioAlterado()
      onFechar()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao cancelar bloqueio")
    } finally {
      setCancelando(false)
      setConfirmCancel(false)
    }
  }

  const podeCancel = linha && linha.estado !== "concluido" && linha.estado !== "cancelado"
  const dataAgenda = linha ? linha.inicio.split("T")[0] : ""
  const badge = linha ? BADGE_MAP[linha.estado] : null
  const origem = linha ? ORIGEM_INFO[linha.origem] : null
  const OrigemIcon = origem?.icon

  const nomeExibido = linha
    ? linha.atendimento_id
      ? (linha.cliente_nome ?? "Cliente")
      : (linha.observacao ?? "Bloqueio manual")
    : ""

  return (
    <>
      <Dialog open={linha !== null} onOpenChange={(v) => { if (!v) onFechar() }}>
        <DialogContent className="w-full max-w-lg rounded-xl bg-card p-0 shadow-xl ring-1 ring-border">
          {/* ── header ──────────────────────────────────────────── */}
          <div className="flex items-start justify-between border-b border-border px-5 py-4">
            <div className="flex flex-col gap-1.5">
              {linha && badge && (
                <>
                  <div className="flex items-center gap-2">
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                    <DialogTitle className="text-sm font-semibold text-text-primary">
                      {formatHorario(linha.inicio)}–{formatHorario(linha.fim)}
                    </DialogTitle>
                  </div>
                  <span className="text-xs text-text-muted">{linha.modelo_nome}</span>
                </>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onFechar}
              aria-label="Fechar"
            >
              <X size={14} />
            </Button>
          </div>

          {/* ── corpo ───────────────────────────────────────────── */}
          {linha && (
            <div className="max-h-[60vh] space-y-4 overflow-y-auto px-5 py-4">
              {/* Informações do bloqueio */}
              <div className="space-y-1.5">
                <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                  Informações
                </p>
                <div className="space-y-1">
                  <InfoRow
                    label="Data"
                    value={`${capitalizar(formatDiaSemana(new Date(linha.inicio)))}, ${formatData(linha.inicio)}`}
                  />
                  <InfoRow label="Duração" value={formatDuracao(linha.inicio, linha.fim)} />
                  {OrigemIcon && origem && (
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
                        Origem{" "}
                      </span>
                      <span className="inline-flex items-center gap-1 text-[13px] text-text-primary">
                        <OrigemIcon size={13} strokeWidth={1.5} className="text-text-muted" />
                        {origem.label}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Cliente (se há atendimento vinculado) */}
              {linha.atendimento_id && (
                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                    Cliente
                  </p>
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] text-text-primary">{nomeExibido}</span>
                    <Button
                      variant="ghost"
                      size="xs"
                      nativeButton={false}
                      className="gap-1 text-text-muted"
                      render={
                        <Link
                          href={`/atendimentos?id=${linha.atendimento_id}`}
                          onClick={onFechar}
                        />
                      }
                    >
                      <ExternalLink size={12} />
                      Ver atendimento
                    </Button>
                  </div>
                </div>
              )}

              {/* Observação (bloqueios manuais sem atendimento) */}
              {!linha.atendimento_id && linha.observacao && (
                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
                    Observação
                  </p>
                  <p className="text-[13px] text-text-primary">{linha.observacao}</p>
                </div>
              )}

            </div>
          )}

          {/* ── footer ──────────────────────────────────────────── */}
          {linha && (
            <div className="flex items-center justify-between border-t border-border px-5 py-3">
              <div>
                {podeCancel && (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => setConfirmCancel(true)}
                    disabled={cancelando}
                  >
                    {cancelando ? "Cancelando…" : "Cancelar bloqueio"}
                  </Button>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                nativeButton={false}
                className="gap-1 text-text-muted"
                render={
                  <Link
                    href={`/agenda?data=${dataAgenda}&bloqueio=${linha.id}`}
                    onClick={onFechar}
                  />
                }
              >
                <ExternalLink size={13} />
                Ver na agenda
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ── AlertDialog: confirmar cancelamento ─────────────────── */}
      <AlertDialog open={confirmCancel} onOpenChange={setConfirmCancel}>
        <AlertDialogContent size="sm" className="bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle>Cancelar bloqueio?</AlertDialogTitle>
            <AlertDialogDescription>
              {linha?.estado === "em_atendimento"
                ? "Este bloqueio está em atendimento. Tem certeza que deseja cancelá-lo?"
                : "O horário será liberado. Esta ação não pode ser desfeita."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={cancelando}>Manter</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={handleCancelar}
              disabled={cancelando}
            >
              {cancelando ? "Cancelando…" : "Cancelar bloqueio"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
