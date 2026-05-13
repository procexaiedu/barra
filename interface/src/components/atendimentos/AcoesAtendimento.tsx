"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import type { AtendimentoOperacional, MotivoPerda } from "@/tipos/atendimentos"

type Dialog = "devolver" | "fechar" | "perder" | null

const motivos: { value: MotivoPerda; label: string }[] = [
  { value: "preco", label: "Preço" },
  { value: "sumiu", label: "Sumiu" },
  { value: "risco", label: "Risco" },
  { value: "indisponibilidade", label: "Indisponibilidade" },
  { value: "fora_de_area", label: "Fora de área" },
  { value: "outro", label: "Outro" },
]

function parseValorFinal(input: string) {
  const normalizado = input
    .replace(/\s/g, "")
    .replace(/\./g, "")
    .replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) ? valor : null
}

function motivoPausaLabel(motivo: AtendimentoOperacional["ia_pausada_motivo"]): string {
  if (motivo === "pix_em_revisao") return "Pix em revisão"
  if (motivo === "handoff_ia") return "Aguardando você"
  if (motivo === "modelo_em_atendimento") return "Modelo atendendo"
  return "—"
}

export function AcoesAtendimento({
  atendimento,
  onDevolver,
  onFechar,
  onPerder,
}: {
  atendimento: AtendimentoOperacional
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
}) {
  const [dialog, setDialog] = useState<Dialog>(null)
  const [submitting, setSubmitting] = useState(false)
  const [valorFinal, setValorFinal] = useState("")
  const [motivo, setMotivo] = useState<MotivoPerda>("sumiu")
  const [observacao, setObservacao] = useState("")
  const [erro, setErro] = useState<string | null>(null)
  const readOnly = atendimento.estado === "Fechado" || atendimento.estado === "Perdido"

  if (readOnly) return null

  const abrirDialog = (proximo: Dialog) => {
    setErro(null)
    setDialog(proximo)
  }

  const handleDevolver = async () => {
    setSubmitting(true)
    try {
      await onDevolver(atendimento.id)
      toast.success(`Atendimento #${atendimento.numero_curto} devolvido para a IA`)
      setDialog(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao devolver")
    } finally {
      setSubmitting(false)
    }
  }

  const handleFechar = async () => {
    const valor = parseValorFinal(valorFinal)
    if (valor === null || valor < 0) {
      setErro("Informe um valor final válido.")
      return
    }
    setSubmitting(true)
    try {
      await onFechar(atendimento.id, valor)
      toast.success(`Atendimento #${atendimento.numero_curto} fechado`)
      setDialog(null)
      setValorFinal("")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao fechar")
    } finally {
      setSubmitting(false)
    }
  }

  const handlePerder = async () => {
    const obs = observacao.trim()
    if (motivo === "outro" && !obs) {
      setErro("Descreva o motivo na observação.")
      return
    }
    setSubmitting(true)
    try {
      await onPerder(atendimento.id, motivo, obs || null)
      toast.success(`Atendimento #${atendimento.numero_curto} marcado como perdido`)
      setDialog(null)
      setObservacao("")
      setMotivo("sumiu")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao marcar como perdido")
    } finally {
      setSubmitting(false)
    }
  }

  const devolverVisivel = atendimento.ia_pausada

  return (
    <div className="flex flex-wrap gap-2">
      {devolverVisivel && (
        <Button variant="primary" onClick={() => abrirDialog("devolver")}>
          Devolver para IA
        </Button>
      )}
      <Button
        variant={devolverVisivel ? "secondary" : "primary"}
        onClick={() => abrirDialog("fechar")}
      >
        Converter
      </Button>
      <Button variant="danger" onClick={() => abrirDialog("perder")}>
        Perder
      </Button>

      <AlertDialog open={dialog === "devolver"} onOpenChange={(open) => !submitting && setDialog(open ? "devolver" : null)}>
        <AlertDialogContent className="w-[min(94vw,28rem)] max-w-none bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Devolver #{atendimento.numero_curto} para a IA?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              A IA volta a responder o cliente na próxima mensagem.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {atendimento.ia_pausada && (
            <div className="flex items-center gap-3 rounded-md border border-border-subtle bg-surface px-3 py-2 text-xs">
              <span className="text-text-muted">IA pausada</span>
              <span className="text-text-primary">{motivoPausaLabel(atendimento.ia_pausada_motivo)}</span>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="primary" onClick={handleDevolver} disabled={submitting}>
              {submitting ? "Devolvendo..." : "Confirmar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={dialog === "fechar"} onOpenChange={(open) => !submitting && setDialog(open ? "fechar" : null)}>
        <AlertDialogContent className="w-[min(94vw,40rem)] max-w-none bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Converter #{atendimento.numero_curto}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              Informe o valor final bruto pago pelo cliente.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border-subtle bg-surface px-3 py-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                Valor acordado
              </p>
              <p className="mt-1 font-serif text-[22px] font-medium leading-none tabular-nums text-gold-500">
                {atendimento.valor_acordado != null
                  ? formatBRL(Number(atendimento.valor_acordado))
                  : "—"}
              </p>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted" htmlFor="valor-final">
                Valor final
              </label>
              <Input
                id="valor-final"
                inputMode="decimal"
                value={valorFinal}
                onChange={(event) => {
                  setValorFinal(event.target.value)
                  setErro(null)
                }}
                placeholder="1200,00"
                className="h-11 text-base"
                autoFocus
              />
            </div>
          </div>
          {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction variant="primary" onClick={handleFechar} disabled={submitting}>
              {submitting ? "Fechando..." : "Confirmar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={dialog === "perder"} onOpenChange={(open) => !submitting && setDialog(open ? "perder" : null)}>
        <AlertDialogContent className="w-[min(94vw,48rem)] max-w-none bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold text-text-primary">
              Marcar #{atendimento.numero_curto} como perdido?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-text-secondary">
              Escolha o motivo da perda. O atendimento será encerrado.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="flex items-center gap-3 text-xs text-text-muted">
            <span>#{atendimento.numero_curto}</span>
            {atendimento.valor_acordado != null && (
              <>
                <span aria-hidden>·</span>
                <span>valor acordado {formatBRL(Number(atendimento.valor_acordado))}</span>
              </>
            )}
          </div>
          <div className="flex flex-col gap-3">
            <div>
              <span className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                Motivo da perda
              </span>
              <div className="grid grid-cols-3 gap-2">
                {motivos.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => {
                      setMotivo(item.value)
                      setErro(null)
                    }}
                    className={cn(
                      "rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                      motivo === item.value
                        ? "border-ring bg-surface-pressed text-text-primary"
                        : "border-border-subtle bg-surface-hover text-text-secondary hover:bg-surface-pressed"
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted" htmlFor="observacao-perda">
                Observação {motivo === "outro" ? "(obrigatória)" : "(opcional)"}
              </label>
              <Input
                id="observacao-perda"
                value={observacao}
                onChange={(event) => {
                  setObservacao(event.target.value)
                  setErro(null)
                }}
                placeholder="Descreva o motivo"
              />
            </div>
            {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              onClick={handlePerder}
              disabled={submitting}
            >
              {submitting ? "Registrando..." : "Confirmar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
