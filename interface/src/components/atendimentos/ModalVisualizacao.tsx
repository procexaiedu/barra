"use client"

import { useCallback, useEffect, useState } from "react"
import { Dialog, DialogBody, DialogCloseButton, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { api, apiFormData } from "@/lib/api"
import { DetalheAtendimento } from "@/components/atendimentos/DetalheAtendimento"
import { nomeCliente } from "@/lib/formatters"
import type {
  AtendimentoDetalheResponse,
  FecharAtendimentoDados,
  MidiaInternaAtendimento,
  MotivoPerda,
} from "@/tipos/atendimentos"

function normalizarDetalheResponse(res: AtendimentoDetalheResponse): AtendimentoDetalheResponse {
  return {
    ...res,
    mensagens: Array.isArray(res.mensagens) ? res.mensagens : [],
    eventos: Array.isArray(res.eventos) ? res.eventos : [],
    comprovantes_pix: Array.isArray(res.comprovantes_pix) ? res.comprovantes_pix : [],
    servicos: Array.isArray(res.servicos) ? res.servicos : [],
    fetiches: Array.isArray(res.fetiches) ? res.fetiches : [],
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
  onCorrigir,
  onExcluir,
  readOnly = false,
}: {
  atendimentoId: string | null
  onClose: () => void
  onDevolver?: (id: string) => Promise<void>
  onFechar?: (id: string, dados: FecharAtendimentoDados) => Promise<void>
  onPerder?: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onAbrirEdicao?: (detalhe: AtendimentoDetalheResponse) => void
  onCorrigir?: (id: string) => void
  onExcluir?: (id: string) => Promise<void>
  readOnly?: boolean
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
    if (!onDevolver) return
    await onDevolver(id)
    onClose()
  }, [onDevolver, onClose])

  const handleFechar = useCallback(async (id: string, dados: FecharAtendimentoDados) => {
    if (!onFechar) return
    await onFechar(id, dados)
    onClose()
  }, [onFechar, onClose])

  const handlePerder = useCallback(async (id: string, motivo: MotivoPerda, observacao: string | null) => {
    if (!onPerder) return
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

  const handleExcluir = useCallback(async (id: string) => {
    if (!onExcluir) return
    await onExcluir(id)
    onClose()
  }, [onExcluir, onClose])

  return (
    <Dialog open={!!atendimentoId} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent size="xl" className="overflow-hidden">
        <DialogTitle className="sr-only">Detalhe do atendimento</DialogTitle>

        <DialogHeader className="justify-between bg-muted">
          <span className="text-sm font-semibold text-text-primary">
            {detalhe ? `${nomeCliente(detalhe.cliente.nome, detalhe.cliente.telefone)} · #${detalhe.atendimento.numero_curto}` : "Atendimento"}
          </span>
          <div className="flex items-center gap-2">
            {detalhe && !readOnly && onAbrirEdicao && (
              <button
                type="button"
                onClick={() => onAbrirEdicao(detalhe)}
                className="rounded-md px-3 py-1 text-xs font-medium text-text-secondary hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Editar
              </button>
            )}
            <DialogCloseButton />
          </div>
        </DialogHeader>

        <DialogBody className="flex min-h-0 flex-col overflow-visible p-6">
          <DetalheAtendimento
            detalhe={detalhe}
            status={status}
            error={error}
            onRetry={() => atendimentoId && carregar(atendimentoId)}
            onDevolver={readOnly ? undefined : handleDevolver}
            onFechar={readOnly ? undefined : handleFechar}
            onPerder={readOnly ? undefined : handlePerder}
            onUploadMidia={readOnly ? undefined : handleUploadMidia}
            onDeletarMidia={readOnly ? undefined : handleDeletarMidia}
            onCorrigir={readOnly || !detalhe || !onCorrigir ? undefined : () => onCorrigir(detalhe.atendimento.id)}
            onExcluir={onExcluir ? handleExcluir : undefined}
            readOnly={readOnly}
          />
        </DialogBody>
      </DialogContent>
    </Dialog>
  )
}
