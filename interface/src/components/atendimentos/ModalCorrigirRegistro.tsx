"use client"

import { useCallback, useEffect, useState } from "react"
import { ApiError, api } from "@/lib/api"
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
import { parseValorFinal } from "@/components/atendimentos/ModalFecharAtendimento"
import type { AtendimentoDetalheResponse, CorrigirRegistroPayload, MotivoPerda } from "@/tipos/atendimentos"

const motivos: { value: MotivoPerda; label: string }[] = [
  { value: "preco", label: "Preço" },
  { value: "sumiu", label: "Sumiu" },
  { value: "risco", label: "Risco" },
  { value: "indisponibilidade", label: "Indisponibilidade" },
  { value: "fora_de_area", label: "Fora de área" },
  { value: "outro", label: "Outro" },
]

type Resultado = "Fechado" | "Perdido"

export function ModalCorrigirRegistro({
  atendimentoId,
  onClose,
  onCorrigir,
}: {
  atendimentoId: string | null
  onClose: () => void
  onCorrigir: (id: string, payload: CorrigirRegistroPayload) => Promise<void>
}) {
  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [resultado, setResultado] = useState<Resultado>("Fechado")
  const [valorFinal, setValorFinal] = useState("")
  const [motivo, setMotivo] = useState<MotivoPerda>("sumiu")
  const [observacao, setObservacao] = useState("")
  const [erro, setErro] = useState<string | null>(null)
  const [precisaConfirmarBloqueio, setPrecisaConfirmarBloqueio] = useState(false)

  const carregar = useCallback(async (id: string) => {
    setCarregando(true)
    setErro(null)
    setPrecisaConfirmarBloqueio(false)
    try {
      const res = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`)
      const a = res.atendimento
      setDetalhe(res)
      setResultado(a.estado === "Perdido" ? "Perdido" : "Fechado")
      setValorFinal(
        a.valor_final != null
          ? String(a.valor_final)
          : a.valor_acordado != null
            ? String(a.valor_acordado)
            : ""
      )
      setMotivo(a.motivo_perda ?? "sumiu")
      setObservacao(a.motivo_perda_obs ?? "")
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao carregar")
    } finally {
      setCarregando(false)
    }
  }, [])

  useEffect(() => {
    if (!atendimentoId) return
    void Promise.resolve().then(() => carregar(atendimentoId))
  }, [atendimentoId, carregar])

  const fechar = () => {
    if (submitting) return
    onClose()
  }

  const handleSalvar = async () => {
    if (!atendimentoId) return
    const payload: CorrigirRegistroPayload = { novo_resultado: resultado }
    if (resultado === "Fechado") {
      const valor = parseValorFinal(valorFinal)
      if (valor === null || valor < 0) {
        setErro("Informe um valor final válido.")
        return
      }
      payload.valor_final = valor
    } else {
      const obs = observacao.trim()
      if (motivo === "outro" && !obs) {
        setErro("Descreva o motivo na observação.")
        return
      }
      payload.motivo = motivo
      payload.observacao = obs || null
    }
    if (precisaConfirmarBloqueio) payload.confirmar_alteracao_bloqueio_finalizado = true
    setSubmitting(true)
    setErro(null)
    try {
      await onCorrigir(atendimentoId, payload)
      onClose()
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        e.details?.campo === "confirmar_alteracao_bloqueio_finalizado"
      ) {
        setPrecisaConfirmarBloqueio(true)
        setErro(null)
      } else {
        setErro(e instanceof Error ? e.message : "Erro ao corrigir resultado")
      }
    } finally {
      setSubmitting(false)
    }
  }

  const numero = detalhe?.atendimento.numero_curto
  const valorAcordado = detalhe?.atendimento.valor_acordado

  return (
    <AlertDialog open={!!atendimentoId} onOpenChange={(o) => !submitting && !o && fechar()}>
      <AlertDialogContent className="w-[min(94vw,44rem)] max-w-none bg-card">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-base font-semibold text-text-primary">
            Corrigir resultado {numero ? `#${numero}` : ""}
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm text-text-secondary">
            Ajuste o resultado registrado. O bloqueio vinculado e o financeiro são reconciliados automaticamente.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {carregando ? (
          <p className="py-6 text-center text-sm text-text-muted">Carregando…</p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-2">
              {(["Fechado", "Perdido"] as Resultado[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setResultado(r)
                    setErro(null)
                  }}
                  className={cn(
                    "rounded-md border px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    resultado === r
                      ? r === "Fechado"
                        ? "border-success-500 bg-success-500/10 text-success-500"
                        : "border-danger-500 bg-danger-500/10 text-danger-500"
                      : "border-border bg-muted text-text-secondary hover:bg-accent hover:text-text-primary"
                  )}
                >
                  {r}
                </button>
              ))}
            </div>

            {resultado === "Fechado" ? (
              <div>
                <label
                  className="mb-1 block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                  htmlFor="corrigir-valor"
                >
                  Valor final
                </label>
                <Input
                  id="corrigir-valor"
                  inputMode="decimal"
                  value={valorFinal}
                  onChange={(e) => {
                    setValorFinal(e.target.value)
                    setErro(null)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      void handleSalvar()
                    }
                  }}
                  placeholder="1200,00"
                  className="h-11 text-base"
                />
                {valorAcordado != null && (
                  <p className="mt-1 text-xs text-text-muted">Acordado: {formatBRL(Number(valorAcordado))}</p>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <div>
                  <span className="mb-2 block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
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
                          "rounded-md border px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          motivo === item.value
                            ? "border-border-brand bg-accent text-text-primary"
                            : "border-border bg-muted text-text-secondary hover:bg-accent hover:text-text-primary"
                        )}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label
                    className="mb-2 block text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted"
                    htmlFor="corrigir-obs"
                  >
                    Observação {motivo === "outro" ? "(obrigatória)" : "(opcional)"}
                  </label>
                  <Input
                    id="corrigir-obs"
                    value={observacao}
                    onChange={(e) => {
                      setObservacao(e.target.value)
                      setErro(null)
                    }}
                    placeholder="Descreva o motivo"
                  />
                </div>
              </div>
            )}

            {precisaConfirmarBloqueio && (
              <div className="rounded-md border border-state-handoff/30 bg-state-handoff/10 p-3 text-[13px] text-text-primary">
                O bloqueio vinculado já está em atendimento ou concluído. Confirmar a correção vai sincronizá-lo mesmo assim. Clique em &ldquo;Confirmar correção&rdquo; novamente para prosseguir.
              </div>
            )}
            {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={submitting} onClick={fechar}>
            Cancelar
          </AlertDialogCancel>
          <AlertDialogAction
            variant={resultado === "Perdido" ? "danger" : "primary"}
            onClick={handleSalvar}
            disabled={submitting || carregando}
          >
            {submitting ? "Salvando…" : precisaConfirmarBloqueio ? "Confirmar correção" : "Salvar correção"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
