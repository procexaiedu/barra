"use client"

import { useState } from "react"
import { ExternalLink, MessageSquare } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
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
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import type { MotivoRejeicao, PixDetalheResponse } from "@/tipos/pix"
import { AtendimentoVinculadoPix } from "./AtendimentoVinculadoPix"
import { isPendente, isRejeitado, motivoRejeicaoOptions } from "./utils"

type DialogAtivo = "validar" | "rejeitar" | "reabrir" | null
type SheetAtivo = "atendimento" | "conversa" | null

export function AcoesPix({
  detalhe,
  onAprovar,
  onRejeitar,
  onReabrir,
}: {
  detalhe: PixDetalheResponse
  onAprovar: (id: string) => Promise<void>
  onRejeitar: (id: string, motivo: MotivoRejeicao, observacao: string | null) => Promise<void>
  onReabrir: (id: string) => Promise<void>
}) {
  const [dialog, setDialog] = useState<DialogAtivo>(null)
  const [sheet, setSheet] = useState<SheetAtivo>(null)
  const [submitting, setSubmitting] = useState(false)
  const [motivo, setMotivo] = useState<MotivoRejeicao>("valor_incorreto")
  const [observacao, setObservacao] = useState("")
  const [erro, setErro] = useState<string | null>(null)

  const pendente = isPendente(detalhe.pix)
  const rejeitado = isRejeitado(detalhe.pix)

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
      const valor = detalhe.pix.valor_extraido !== null
        ? formatBRL(detalhe.pix.valor_extraido)
        : "comprovante"
      toast.success(`Pix de ${valor} validado`)
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
  const podeAbrirConversa = detalhe.conversa !== null

  const nomeCliente =
    detalhe.conversa !== null
      ? (detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone))
      : null

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
      {(rejeitado || podeAbrirAtendimento || podeAbrirConversa) && (
        <div className="flex flex-wrap gap-2">
          {rejeitado && (
            <Button variant="secondary" onClick={() => abrir("reabrir")}>
              Reabrir Pix
            </Button>
          )}
          {podeAbrirAtendimento && (
            <Button variant="ghost" size="sm" onClick={() => setSheet("atendimento")}>
              <ExternalLink className="h-3.5 w-3.5" />
              Atendimento #{detalhe.atendimento?.numero_curto}
            </Button>
          )}
          {podeAbrirConversa && (
            <Button variant="ghost" size="sm" onClick={() => setSheet("conversa")}>
              <MessageSquare className="h-3.5 w-3.5" />
              Conversa
            </Button>
          )}
        </div>
      )}

      <Sheet open={sheet === "atendimento"} onOpenChange={(o) => setSheet(o ? "atendimento" : null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Atendimento #{detalhe.atendimento?.numero_curto}</SheetTitle>
          </SheetHeader>
          <SheetBody>
            <AtendimentoVinculadoPix atendimento={detalhe.atendimento} />
          </SheetBody>
        </SheetContent>
      </Sheet>

      <Sheet open={sheet === "conversa"} onOpenChange={(o) => setSheet(o ? "conversa" : null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Conversa com {detalhe.modelo.nome}</SheetTitle>
          </SheetHeader>
          <SheetBody className="space-y-3">
            {nomeCliente && (
              <div>
                <p className="text-xs text-text-muted">Cliente</p>
                <p className="text-sm text-text-primary">{nomeCliente}</p>
              </div>
            )}
            <div>
              <p className="text-xs text-text-muted">Modelo</p>
              <p className="text-sm text-text-primary">{detalhe.modelo.nome}</p>
            </div>
            <a
              href="/clientes"
              className="inline-flex items-center gap-1.5 text-sm text-text-link underline-offset-4 hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Abrir conversa completa →
            </a>
          </SheetBody>
        </SheetContent>
      </Sheet>

      <AlertDialog open={dialog === "validar"} onOpenChange={(o) => !submitting && setDialog(o ? "validar" : null)}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Validar Pix manualmente?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A modelo recebe a saída confirmada no grupo de Coordenação e o atendimento avança para Confirmado. Esta decisão é definitiva.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting} onClick={fechar}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="primary" onClick={handleAprovar} disabled={submitting}>
              {submitting ? "Validando…" : "Confirmar validação"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={dialog === "rejeitar"} onOpenChange={(o) => !submitting && setDialog(o ? "rejeitar" : null)}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Rejeitar Pix?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A IA envia a mensagem correspondente ao motivo escolhido pedindo um novo
              comprovante. O atendimento continua aguardando o Pix.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3">
            <div>
              <label
                className="mb-2 block text-sm font-medium text-text-primary"
                htmlFor="motivo-rejeicao"
              >
                Motivo
              </label>
              <select
                id="motivo-rejeicao"
                value={motivo}
                onChange={(event) => {
                  setMotivo(event.target.value as MotivoRejeicao)
                  setErro(null)
                }}
                className="h-9 w-full rounded-lg border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                {motivoRejeicaoOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label
                className="mb-2 block text-sm font-medium text-text-primary"
                htmlFor="observacao-rejeicao"
              >
                Observação interna {motivo === "outro" ? "" : "(opcional)"}
              </label>
              <Textarea
                id="observacao-rejeicao"
                value={observacao}
                onChange={(event) => {
                  setObservacao(event.target.value)
                  setErro(null)
                }}
                placeholder="Não exibida ao cliente"
                rows={3}
                maxLength={500}
              />
              {observacao.length >= 400 && (
                <p className="mt-1 text-right text-xs text-text-muted">
                  {observacao.length}/500
                </p>
              )}
            </div>
            {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting} onClick={fechar}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="danger" onClick={handleRejeitar} disabled={submitting}>
              {submitting ? "Rejeitando…" : "Confirmar rejeição"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={dialog === "reabrir"} onOpenChange={(o) => !submitting && setDialog(o ? "reabrir" : null)}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Reabrir Pix?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              O Pix volta para revisão. O atendimento não é alterado.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting} onClick={fechar}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="primary" onClick={handleReabrir} disabled={submitting}>
              {submitting ? "Reabrindo…" : "Confirmar reabertura"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
