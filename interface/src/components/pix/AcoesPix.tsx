"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
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
import { formatBRL } from "@/lib/formatters"
import type { MotivoRejeicao, PixDetalheResponse } from "@/tipos/pix"
import { isPendente, isRejeitado, motivoRejeicaoOptions } from "./utils"

type DialogAtivo = "validar" | "rejeitar" | "reabrir" | null

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
  const router = useRouter()
  const [dialog, setDialog] = useState<DialogAtivo>(null)
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
      setErro("Informe a observação para motivo outro.")
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

  return (
    <div className="flex flex-wrap gap-2">
      {pendente && (
        <Button variant="primary" onClick={() => abrir("validar")}>
          Validar Pix
        </Button>
      )}
      {pendente && (
        <Button variant="danger" onClick={() => abrir("rejeitar")}>
          Rejeitar Pix
        </Button>
      )}
      {rejeitado && (
        <Button variant="secondary" onClick={() => abrir("reabrir")}>
          Reabrir Pix
        </Button>
      )}
      {podeAbrirAtendimento && (
        <Button variant="ghost" onClick={() => router.push("/atendimentos")}>
          Abrir atendimento
        </Button>
      )}
      {podeAbrirConversa && (
        <Button variant="ghost" onClick={() => router.push("/crm")}>
          Abrir conversa
        </Button>
      )}

      <AlertDialog open={dialog === "validar"} onOpenChange={(o) => !submitting && setDialog(o ? "validar" : null)}>
        <AlertDialogContent className="max-w-md bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Validar Pix manualmente?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A IA será reativada para a modelo: card &quot;saída confirmada&quot; será enviado no
              grupo de Coordenação por modelo, a IA pausa por modelo_em_atendimento e o
              atendimento avança para Confirmado. Esta decisão é definitiva.
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
              Selecionando o motivo abaixo, a IA enviará a mensagem padrão correspondente
              ao cliente pedindo um novo comprovante. O atendimento permanece no estado
              atual e a IA continua pausada por pix_em_revisao até receber novo Pix.
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
              O Pix volta para a fila de revisão. O atendimento não é alterado.
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
