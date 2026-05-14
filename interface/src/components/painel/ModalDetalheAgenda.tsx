"use client"

import { useState, useEffect, type ReactNode } from "react"
import Link from "next/link"
import { Bot, User, Hand, ExternalLink, X, Clock, Calendar, Timer, Users, FileText } from "lucide-react"
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
import { cn } from "@/lib/utils"
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

// ── sub-componentes ───────────────────────────────────────────────────────────

function StatTile({ label, icone, children }: { label: string; icone?: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-muted px-4 py-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] leading-none text-text-muted">
        {icone}
        <span>{label}</span>
      </p>
      <div className="text-[14px] leading-tight text-text-primary">{children}</div>
    </div>
  )
}

function SecaoBloco({
  titulo,
  icone,
  children,
}: {
  titulo: string
  icone: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <header className="mb-3 flex items-center gap-2">
        {icone}
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
          {titulo}
        </h3>
      </header>
      {children}
    </section>
  )
}

// ── componente principal ──────────────────────────────────────────────────────

export function ModalDetalheAgenda({
  linha,
  onFechar,
  onBloqueioAlterado,
  onAbrirHistorico,
}: {
  linha: LinhaAgenda | null
  onFechar: () => void
  onBloqueioAlterado: () => void
  onAbrirHistorico?: (atendimentoId: string) => void
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

  const temCliente = linha?.atendimento_id != null
  const temObservacao = linha != null && !linha.atendimento_id && !!linha.observacao

  return (
    <>
      <Dialog open={linha !== null} onOpenChange={(v) => { if (!v) onFechar() }}>
        <DialogContent className="flex w-[min(96vw,80rem)] max-h-[92vh] min-h-[60vh] flex-col rounded-xl bg-card p-0 shadow-xl ring-1 ring-border">
          {/* ── header ──────────────────────────────────────────── */}
          <header className="flex items-start justify-between gap-3 border-b border-border px-8 py-4">
            <div className="flex flex-col gap-1.5">
              {linha && badge && (
                <>
                  <div className="flex flex-wrap items-center gap-2.5">
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                    <DialogTitle className="text-base font-semibold text-text-primary">
                      Bloqueio de agenda
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
          </header>

          {/* ── corpo ───────────────────────────────────────────── */}
          {linha && (
            <div className="flex-1 px-8 py-6">
              {/* Hero KPI: horário em destaque */}
              <div className="mb-6 overflow-hidden rounded-md border border-border bg-muted">
                <div className="flex flex-wrap items-end justify-between gap-3 px-6 py-5">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                      Horário
                    </p>
                    <p className="mt-1 font-serif text-[40px] font-medium leading-none tabular-nums text-gold-500">
                      {formatHorario(linha.inicio)}<span className="px-1 text-text-muted">–</span>{formatHorario(linha.fim)}
                    </p>
                  </div>
                  {nomeExibido && (
                    <div className="text-right">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                        {temCliente ? "Cliente" : "Bloqueio"}
                      </p>
                      <p className="mt-1 max-w-[360px] truncate text-[18px] font-medium text-text-primary">
                        {nomeExibido}
                      </p>
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-px border-t border-border bg-border sm:grid-cols-4">
                  <StatTile
                    label="Data"
                    icone={<Calendar size={11} strokeWidth={1.75} className="text-info-500" />}
                  >
                    <span className="capitalize">{formatDiaSemana(new Date(linha.inicio))}</span>
                    <span className="ml-1 text-text-muted">· {formatData(linha.inicio)}</span>
                  </StatTile>
                  <StatTile
                    label="Duração"
                    icone={<Timer size={11} strokeWidth={1.75} className="text-text-muted" />}
                  >
                    {formatDuracao(linha.inicio, linha.fim)}
                  </StatTile>
                  <StatTile
                    label="Modelo"
                    icone={<Users size={11} strokeWidth={1.75} className="text-text-muted" />}
                  >
                    <span className="truncate">{linha.modelo_nome}</span>
                  </StatTile>
                  {OrigemIcon && origem && (
                    <StatTile
                      label="Origem"
                      icone={<OrigemIcon size={11} strokeWidth={1.75} className="text-text-muted" />}
                    >
                      {origem.label}
                    </StatTile>
                  )}
                </div>
              </div>

              {/* Blocos de contexto */}
              {(temCliente || temObservacao) && (
                <div className={cn(
                  "grid gap-6",
                  temCliente && temObservacao ? "lg:grid-cols-2" : "grid-cols-1"
                )}>
                  {temCliente && (
                    <SecaoBloco
                      titulo="Cliente vinculado"
                      icone={<User size={14} strokeWidth={1.75} className="text-text-muted" />}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[14px] text-text-primary">{nomeExibido}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="shrink-0 gap-1 text-text-muted"
                          onClick={() => {
                            const id = linha.atendimento_id
                            onFechar()
                            if (id) onAbrirHistorico?.(id)
                          }}
                        >
                          <ExternalLink size={12} />
                          Ver atendimento
                        </Button>
                      </div>
                    </SecaoBloco>
                  )}

                  {temObservacao && (
                    <SecaoBloco
                      titulo="Observação"
                      icone={<FileText size={14} strokeWidth={1.75} className="text-text-muted" />}
                    >
                      <p className="text-[14px] leading-relaxed text-text-secondary">
                        {linha.observacao}
                      </p>
                    </SecaoBloco>
                  )}
                </div>
              )}

              {!temCliente && !temObservacao && (
                <SecaoBloco
                  titulo="Sobre este bloqueio"
                  icone={<Clock size={14} strokeWidth={1.75} className="text-text-muted" />}
                >
                  <p className="text-[14px] text-text-disabled">
                    Sem cliente vinculado e sem observação. Tudo o que precisa saber está no resumo acima.
                  </p>
                </SecaoBloco>
              )}
            </div>
          )}

          {/* ── footer ──────────────────────────────────────────── */}
          {linha && (
            <footer className="flex items-center justify-between border-t border-border px-8 py-3">
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
            </footer>
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
