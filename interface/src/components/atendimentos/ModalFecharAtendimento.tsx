"use client"

import { useState } from "react"
import { toast } from "sonner"
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
import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { FecharAtendimentoDados, FormaPagamento } from "@/tipos/atendimentos"

const FORMAS: ReadonlyArray<readonly [FormaPagamento, string]> = [
  ["pix", "PIX"],
  ["dinheiro", "Dinheiro"],
  ["cartao", "Cartão"],
]

export function parseValorFinal(input: string) {
  const normalizado = input
    .replace(/\s/g, "")
    .replace(/\./g, "")
    .replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) ? valor : null
}

export function ModalFecharAtendimento({
  open,
  numeroCurto,
  valorAcordado,
  formaPagamentoInicial,
  onFechar,
  onCancelar,
}: {
  open: boolean
  numeroCurto: number | null
  valorAcordado: number | string | null
  formaPagamentoInicial?: string | null
  onFechar: (dados: FecharAtendimentoDados) => Promise<void>
  onCancelar: () => void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [valorFinal, setValorFinal] = useState("")
  const [formaPagamento, setFormaPagamento] = useState<FormaPagamento | "">("")
  const [isentarTaxa, setIsentarTaxa] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [aberto, setAberto] = useState(open)

  // Ressincroniza a forma sugerida (e zera a isenção) quando o modal abre — o componente é
  // reusado entre atendimentos. Padrão React de ajustar estado em render (sem efeito).
  if (open !== aberto) {
    setAberto(open)
    if (open) {
      setFormaPagamento(
        FORMAS.some(([v]) => v === formaPagamentoInicial)
          ? (formaPagamentoInicial as FormaPagamento)
          : "",
      )
      setIsentarTaxa(false)
    }
  }

  const fechar = () => {
    if (submitting) return
    setValorFinal("")
    setErro(null)
    onCancelar()
  }

  const handleFechar = async () => {
    const valor = parseValorFinal(valorFinal)
    if (valor === null || valor < 0) {
      setErro("Informe um valor final válido.")
      return
    }
    setSubmitting(true)
    try {
      await onFechar({
        valorFinal: valor,
        formaPagamento: formaPagamento || null,
        isentarTaxa: formaPagamento === "cartao" ? isentarTaxa : false,
      })
      setValorFinal("")
      setErro(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao fechar")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !submitting && !o && fechar()}>
      <AlertDialogContent className="w-[min(94vw,40rem)] max-w-none bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-base font-semibold text-text-primary">
            Fechar #{numeroCurto}?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm text-text-secondary">
            Informe o valor final bruto pago pelo cliente. Isto encerra o atendimento e conclui o bloqueio vinculado.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md bg-muted px-3 py-2.5">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
              Valor acordado
            </p>
            <p className="mt-1 font-mono text-2xl font-semibold leading-none tabular-nums text-gold-500">
              {valorAcordado != null ? formatBRL(Number(valorAcordado)) : "—"}
            </p>
          </div>
          <div>
            <label
              className="mb-1 block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
              htmlFor="valor-final-modal"
            >
              Valor final
            </label>
            <Input
              id="valor-final-modal"
              inputMode="decimal"
              value={valorFinal}
              onChange={(event) => {
                setValorFinal(event.target.value)
                setErro(null)
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  void handleFechar()
                }
              }}
              placeholder="1200,00"
              className="h-11 text-base"
              autoFocus
            />
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            Forma de pagamento
          </p>
          <div className="flex gap-2">
            {FORMAS.map(([valor, rotulo]) => (
              <button
                key={valor}
                type="button"
                onClick={() => setFormaPagamento(valor)}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                  formaPagamento === valor
                    ? "border-border-brand bg-accent text-text-brand"
                    : "border-border text-text-muted hover:border-border-strong hover:text-text-secondary",
                )}
              >
                {rotulo}
              </button>
            ))}
          </div>
          {formaPagamento === "cartao" && (
            <>
              <label className="mt-2 flex items-center gap-2 text-[13px] text-text-secondary">
                <input
                  type="checkbox"
                  checked={isentarTaxa}
                  onChange={(event) => setIsentarTaxa(event.target.checked)}
                  className="h-4 w-4 accent-gold-500"
                />
                Isentar taxa de cartão
              </label>
              {!isentarTaxa && (
                <p className="mt-1 text-xs text-text-muted">
                  A taxa de cartão padrão será aplicada sobre o serviço; repasse e comissão usam o valor líquido.
                </p>
              )}
            </>
          )}
        </div>
        {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={fechar}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction variant="primary" onClick={handleFechar} disabled={submitting}>
            {submitting ? "Fechando..." : "Confirmar"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
