"use client"

import { useCallback, useEffect, useState } from "react"
import { X } from "lucide-react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { api, apiFormData } from "@/lib/api"
import { DetalheAtendimento } from "@/components/atendimentos/DetalheAtendimento"
import { formatTelefone } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, MidiaInternaAtendimento, MotivoPerda } from "@/tipos/atendimentos"

function normalizarDetalheResponse(res: AtendimentoDetalheResponse): AtendimentoDetalheResponse {
  return {
    ...res,
    mensagens: Array.isArray(res.mensagens) ? res.mensagens : [],
    eventos: Array.isArray(res.eventos) ? res.eventos : [],
    comprovantes_pix: Array.isArray(res.comprovantes_pix) ? res.comprovantes_pix : [],
    servicos: Array.isArray(res.servicos) ? res.servicos : [],
    midias_internas: Array.isArray(res.midias_internas) ? res.midias_internas : [],
  }
}

export function ModalVisualizacao({
  atendimentoId,
  onClose,
  onDevolver,
  onFechar,
  onPerder,
  onAbrirEdicao,
}: {
  atendimentoId: string | null
  onClose: () => void
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onAbrirEdicao: (detalhe: AtendimentoDetalheResponse) => void
}) {
  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [error, setError] = useState<string | null>(null)

  const carregar = useCallback(async (id: string) => {
    setStatus("loading")
    setDetalhe(null)
    try {
      const res = normalizarDetalheResponse(await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`))
      setDetalhe(res)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Erro ao carregar")
    }
  }, [])

  useEffect(() => {
    if (!atendimentoId) return
    void Promise.resolve().then(() => carregar(atendimentoId))
  }, [atendimentoId, carregar])

  const handleDevolver = useCallback(async (id: string) => {
    await onDevolver(id)
    onClose()
  }, [onDevolver, onClose])

  const handleFechar = useCallback(async (id: string, valorFinal: number) => {
    await onFechar(id, valorFinal)
    onClose()
  }, [onFechar, onClose])

  const handlePerder = useCallback(async (id: string, motivo: MotivoPerda, observacao: string | null) => {
    await onPerder(id, motivo, observacao)
    onClose()
  }, [onPerder, onClose])

  const handleUploadMidia = useCallback(async (atendimentoId: string, file: File, tipo: string) => {
    const form = new FormData()
    form.append("arquivo", file)
    form.append("tipo", tipo)
    const nova = await apiFormData<MidiaInternaAtendimento>(`/v1/atendimentos/${atendimentoId}/midias`, form)
    setDetalhe((prev) => prev ? { ...prev, midias_internas: [nova, ...prev.midias_internas] } : prev)
  }, [])

  const handleDeletarMidia = useCallback(async (atendimentoId: string, midiaId: string) => {
    await api(`/v1/atendimentos/${atendimentoId}/midias/${midiaId}`, { method: "DELETE" })
    setDetalhe((prev) => prev ? { ...prev, midias_internas: prev.midias_internas.filter((m) => m.id !== midiaId) } : prev)
  }, [])

  return (
    <Dialog open={!!atendimentoId} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex h-[min(88vh,820px)] w-[min(96vw,1280px)] max-w-[1280px] flex-col overflow-hidden bg-surface p-0">
        <DialogTitle className="sr-only">Detalhe do atendimento</DialogTitle>

        <div className="flex flex-none items-center justify-between border-b border-border bg-surface px-5 py-3">
          <span className="text-sm font-semibold text-text-primary">
            {detalhe ? `${detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)} · #${detalhe.atendimento.numero_curto}` : "Atendimento"}
          </span>
          <div className="flex items-center gap-2">
            {detalhe && (
              <button
                type="button"
                onClick={() => onAbrirEdicao(detalhe)}
                className="rounded-md px-3 py-1 text-xs font-medium text-text-secondary hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Editar
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Fechar"
              className="rounded-md p-1 text-text-muted hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col p-5">
          <DetalheAtendimento
            detalhe={detalhe}
            status={status}
            error={error}
            onRetry={() => atendimentoId && carregar(atendimentoId)}
            onDevolver={handleDevolver}
            onFechar={handleFechar}
            onPerder={handlePerder}
            onUploadMidia={handleUploadMidia}
            onDeletarMidia={handleDeletarMidia}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}
