"use client"

import { useState } from "react"
import {
  CheckCircle2,
  Eye,
  RotateCcw,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
} from "@/components/ui/alert-dialog"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { MotivoRejeicao, PixDetalheResponse } from "@/tipos/pix"
import {
  badgeForStatusPix,
  isPendente,
  isRejeitado,
  motivoRejeicaoOptions,
  motivoRevisaoLabel,
  statusItemPix,
} from "./utils"

type DialogAtivo = "validar" | "rejeitar" | "reabrir" | null

export function AcoesPix({
  detalhe,
  onAprovar,
  onRejeitar,
  onReabrir,
  onAbrirAtendimento,
}: {
  detalhe: PixDetalheResponse
  onAprovar: (id: string) => Promise<void>
  onRejeitar: (id: string, motivo: MotivoRejeicao, observacao: string | null) => Promise<void>
  onReabrir: (id: string) => Promise<void>
  onAbrirAtendimento?: () => void
}) {
  const [dialog, setDialog] = useState<DialogAtivo>(null)
  const [submitting, setSubmitting] = useState(false)
  const [motivo, setMotivo] = useState<MotivoRejeicao>("valor_incorreto")
  const [observacao, setObservacao] = useState("")
  const [erro, setErro] = useState<string | null>(null)

  const pendente = isPendente(detalhe.pix)
  const rejeitado = isRejeitado(detalhe.pix)
  const status = statusItemPix(detalhe.pix.decisao_pipeline, detalhe.pix.decisao_final)
  const statusBadge = badgeForStatusPix(status)

  const valorLabel =
    detalhe.pix.valor_extraido !== null
      ? formatBRL(detalhe.pix.valor_extraido)
      : null
  const clienteLabel =
    detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const titularLabel = detalhe.pix.titular_extraido
  const motivoRevisao =
    detalhe.pix.motivo_em_revisao && detalhe.pix.motivo_em_revisao in motivoRevisaoLabel
      ? motivoRevisaoLabel[detalhe.pix.motivo_em_revisao]
      : null

  const abrir = (proximo: DialogAtivo) => {
    setErro(null)
    setDialog(proximo)
  }

  const fechar = () => {
    if (submitting) return
    setDialog(null)
  }

  const handleAprovar = async () => {
    setSubmitting(true)
    try {
      await onAprovar(detalhe.pix.id)
      toast.success(`Pix de ${valorLabel ?? "comprovante"} validado`)
      setDialog(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao validar Pix")
    } finally {
      setSubmitting(false)
    }
  }

  const handleRejeitar = async () => {
    const obs = observacao.trim()
    if (motivo === "outro" && !obs) {
      setErro("Descreva o motivo na observação.")
      return
    }
    if (obs.length > 500) {
      setErro("Observação não pode exceder 500 caracteres.")
      return
    }
    setSubmitting(true)
    try {
      await onRejeitar(detalhe.pix.id, motivo, obs || null)
      toast.success("Pix rejeitado")
      setDialog(null)
      setObservacao("")
      setMotivo("valor_incorreto")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao rejeitar Pix")
    } finally {
      setSubmitting(false)
    }
  }

  const handleReabrir = async () => {
    setSubmitting(true)
    try {
      await onReabrir(detalhe.pix.id)
      toast.success("Pix reaberto para revisão")
      setDialog(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao reabrir Pix")
    } finally {
      setSubmitting(false)
    }
  }

  const podeAbrirAtendimento = detalhe.atendimento !== null

  return (
    <div className="space-y-2">
      {pendente && (
        <div className="grid grid-cols-2 gap-2">
          <Button
            className="h-12 bg-emerald-600 text-white hover:bg-emerald-700"
            onClick={() => abrir("validar")}
          >
            Validar Pix
          </Button>
          <Button
            variant="destructive"
            className="h-12"
            onClick={() => abrir("rejeitar")}
          >
            Rejeitar Pix
          </Button>
        </div>
      )}
      {(rejeitado || podeAbrirAtendimento) && (
        <div className="flex flex-wrap gap-2">
          {rejeitado && (
            <Button variant="secondary" onClick={() => abrir("reabrir")}>
              Reabrir Pix
            </Button>
          )}
          {podeAbrirAtendimento && onAbrirAtendimento && (
            <Button variant="ghost" size="sm" onClick={onAbrirAtendimento}>
              <Eye className="h-3.5 w-3.5" />
              Ver atendimento
            </Button>
          )}
        </div>
      )}

      {/* ═══════════════════════ VALIDAR ═══════════════════════ */}
      <AlertDialog
        open={dialog === "validar"}
        onOpenChange={(o) => !submitting && setDialog(o ? "validar" : null)}
      >
        <AlertDialogContent className="flex w-[min(96vw,44rem)] max-w-none flex-col gap-0 overflow-hidden rounded-xl border border-border bg-popover p-0">
          {/* Header */}
          <div className="flex items-start gap-3 border-b border-border px-8 py-4">
            <span className="mt-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
              <CheckCircle2 size={22} strokeWidth={1.8} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-text-primary">
                Validar Pix manualmente?
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                A modelo recebe a saída confirmada no grupo de Coordenação e o atendimento avança para Confirmado.
                Esta decisão é definitiva.
              </p>
            </div>
          </div>

          {/* Hero */}
          <div className="grid grid-cols-3 gap-3 px-8 py-4">
            <HeroBlock label="Valor">
              {valorLabel ? (
                <span className="text-2xl font-semibold leading-none text-text-primary">
                  {valorLabel}
                </span>
              ) : (
                <span className="text-base text-text-muted">Não identificado</span>
              )}
            </HeroBlock>
            <HeroBlock label="Cliente">
              <span className="text-sm text-text-primary">{clienteLabel}</span>
            </HeroBlock>
            <HeroBlock label="Remetente do comprovante">
              {titularLabel ? (
                <span className="text-sm text-text-primary">{titularLabel}</span>
              ) : (
                <span className="text-sm text-text-muted">Não identificado</span>
              )}
            </HeroBlock>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/40 px-8 py-4">
            <AlertDialogCancel disabled={submitting} onClick={fechar}>
              Cancelar
            </AlertDialogCancel>
            <AlertDialogAction
              variant="primary"
              className="bg-emerald-600 text-white hover:bg-emerald-500"
              onClick={handleAprovar}
              disabled={submitting}
            >
              {submitting ? "Validando…" : "Confirmar validação"}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      {/* ═══════════════════════ REJEITAR ═══════════════════════ */}
      <AlertDialog
        open={dialog === "rejeitar"}
        onOpenChange={(o) => !submitting && setDialog(o ? "rejeitar" : null)}
      >
        <AlertDialogContent className="flex w-[min(96vw,68rem)] max-w-none flex-col gap-0 overflow-hidden rounded-xl border border-border bg-popover p-0">
          {/* Header */}
          <div className="flex items-start gap-3 border-b border-border px-8 py-4">
            <span className="mt-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-red-500">
              <XCircle size={22} strokeWidth={1.8} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-text-primary">
                Rejeitar Pix?
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                A IA envia a mensagem correspondente ao motivo escolhido pedindo um novo
                comprovante. O atendimento continua aguardando o Pix.
              </p>
            </div>
            <Badge variant={statusBadge.variant}>{statusBadge.label}</Badge>
          </div>

          {/* Hero strip */}
          <div className="grid grid-cols-3 gap-3 border-b border-border px-8 py-4">
            <HeroBlock label="Valor">
              {valorLabel ? (
                <span className="text-xl font-semibold leading-none text-text-primary">
                  {valorLabel}
                </span>
              ) : (
                <span className="text-sm text-text-muted">Não identificado</span>
              )}
            </HeroBlock>
            <HeroBlock label="Cliente">
              <span className="text-sm text-text-primary">{clienteLabel}</span>
            </HeroBlock>
            <HeroBlock label={motivoRevisao ? "Motivo da revisão" : "Modelo"}>
              {motivoRevisao ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-state-handoff">
                  <RotateCcw size={13} strokeWidth={1.8} />
                  {motivoRevisao}
                </span>
              ) : (
                <span className="text-sm text-text-primary">{detalhe.modelo.nome}</span>
              )}
            </HeroBlock>
          </div>

          {/* Body 2-col */}
          <div className="grid flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-8 gap-y-4 px-8 py-6">
            {/* Coluna esquerda: motivos */}
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Motivo da rejeição
              </p>
              <div className="mt-3 grid grid-cols-1 gap-1.5">
                {motivoRejeicaoOptions.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => {
                      setMotivo(o.value)
                      setErro(null)
                    }}
                    className={cn(
                      "flex items-center justify-between rounded-md border px-3.5 py-2.5 text-left text-sm transition-colors",
                      motivo === o.value
                        ? "border-red-500/70 bg-red-500/10 text-text-primary"
                        : "border-border bg-muted text-text-secondary hover:border-border-strong hover:text-text-primary",
                    )}
                  >
                    <span>{o.label}</span>
                    {motivo === o.value && (
                      <span aria-hidden className="size-2 rounded-full bg-red-500" />
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Coluna direita: observação */}
            <div className="flex flex-col">
              <div className="flex items-baseline justify-between">
                <Label
                  htmlFor="rej-obs"
                  className="text-xs font-semibold uppercase tracking-wider text-text-muted"
                >
                  Observação interna{" "}
                  <span className="text-text-muted normal-case tracking-normal">
                    {motivo === "outro" ? "(obrigatória)" : "(opcional)"}
                  </span>
                </Label>
                <span className="text-xs text-text-muted">{observacao.length}/500</span>
              </div>
              <Textarea
                id="rej-obs"
                value={observacao}
                onChange={(event) => {
                  setObservacao(event.target.value)
                  setErro(null)
                }}
                placeholder="Não exibida ao cliente"
                rows={8}
                maxLength={500}
                className="mt-3 min-h-[180px] flex-1 resize-none"
              />
              <p className="mt-2 text-xs text-text-muted">
                Aparece apenas no histórico interno e no card de Coordenação por modelo.
              </p>
              {erro && <p className="mt-2 text-[13px] text-danger-500">{erro}</p>}
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/40 px-8 py-4">
            <AlertDialogCancel disabled={submitting} onClick={fechar}>
              Cancelar
            </AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              onClick={handleRejeitar}
              disabled={submitting}
            >
              {submitting ? "Rejeitando…" : "Confirmar rejeição"}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>

      {/* ═══════════════════════ REABRIR ═══════════════════════ */}
      <AlertDialog
        open={dialog === "reabrir"}
        onOpenChange={(o) => !submitting && setDialog(o ? "reabrir" : null)}
      >
        <AlertDialogContent className="flex w-[min(96vw,40rem)] max-w-none flex-col gap-0 overflow-hidden rounded-xl border border-border bg-popover p-0">
          {/* Header */}
          <div className="flex items-start gap-3 border-b border-border px-8 py-4">
            <span className="mt-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-state-handoff/15 text-state-handoff">
              <RotateCcw size={20} strokeWidth={1.8} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-text-primary">
                Reabrir Pix?
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                O Pix volta para revisão. O atendimento não é alterado e nenhuma mensagem é enviada ao cliente.
              </p>
            </div>
          </div>

          {/* Hero */}
          <div className="grid grid-cols-2 gap-3 px-8 py-4">
            <HeroBlock label="Valor">
              {valorLabel ? (
                <span className="text-xl font-semibold leading-none text-text-primary">
                  {valorLabel}
                </span>
              ) : (
                <span className="text-base text-text-muted">Não identificado</span>
              )}
            </HeroBlock>
            <HeroBlock label="Cliente">
              <span className="text-sm text-text-primary">{clienteLabel}</span>
            </HeroBlock>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border bg-muted/40 px-8 py-4">
            <AlertDialogCancel disabled={submitting} onClick={fechar}>
              Cancelar
            </AlertDialogCancel>
            <AlertDialogAction
              variant="primary"
              onClick={handleReabrir}
              disabled={submitting}
            >
              {submitting ? "Reabrindo…" : "Confirmar reabertura"}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function HeroBlock({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-3.5 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      <div className="mt-1.5">{children}</div>
    </div>
  )
}
