"use client"

import { useEffect, useState } from "react"
import { ExternalLink, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogClose,
  DialogContent,
} from "@/components/ui/dialog"
import { BannerErro } from "@/components/layout/BannerErro"
import type { ComprovanteUrlResponse, MotivoRejeicao, PixDetalhe } from "@/tipos/pix"
import { motivoRejeicaoOptions } from "./utils"

type Fase = "view" | "rejecting"

export function DialogVisualizarComprovante({
  open,
  onOpenChange,
  pix,
  comprovante,
  comprovanteStatus,
  onTentarNovamente,
  onAprovar,
  onRejeitar,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  pix: PixDetalhe | null
  comprovante: ComprovanteUrlResponse | null
  comprovanteStatus: "idle" | "loading" | "success" | "error"
  onTentarNovamente: () => void
  onAprovar?: () => Promise<void>
  onRejeitar?: (motivo: MotivoRejeicao, observacao: string | null) => Promise<void>
}) {
  const [fase, setFase] = useState<Fase>("view")
  const [motivo, setMotivo] = useState<MotivoRejeicao>("valor_incorreto")
  const [observacao, setObservacao] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setFase("view")
      setMotivo("valor_incorreto")
      setObservacao("")
      setErro(null)
    }
  }, [open])

  const isPdf = pix?.mime_type === "application/pdf"
  const isImage = pix?.mime_type?.startsWith("image/")
  const pendente = pix?.decisao_final === null
  const isMinioUrl = comprovante?.url.startsWith("minio://")
  const hasActions =
    pendente && comprovanteStatus === "success" && !isMinioUrl && onAprovar && onRejeitar

  const handleAprovar = async () => {
    if (!onAprovar) return
    setSubmitting(true)
    try {
      await onAprovar()
      toast.success("Pix validado")
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao validar Pix")
    } finally {
      setSubmitting(false)
    }
  }

  const handleRejeitar = async () => {
    if (!onRejeitar) return
    const obs = observacao.trim()
    if (motivo === "outro" && !obs) {
      setErro("Descreva o motivo na observação.")
      return
    }
    setSubmitting(true)
    setErro(null)
    try {
      await onRejeitar(motivo, obs || null)
      toast.success("Pix rejeitado")
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao rejeitar Pix")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[100vh] w-[100vw] flex-col bg-ink-0 p-0">
        {/* Header com botão fechar */}
        <div className="flex flex-none items-center justify-end p-2">
          <DialogClose
            render={
              <Button variant="ghost" size="icon" aria-label="Fechar">
                <X size={20} strokeWidth={1.5} />
              </Button>
            }
          />
        </div>

        {/* Área do comprovante — clicar no fundo escuro fecha o dialog */}
        <div
          className="flex flex-1 items-center justify-center overflow-hidden"
          onClick={() => !submitting && onOpenChange(false)}
        >
          <div
            className="flex max-h-full max-w-full flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            {comprovanteStatus === "error" ? (
              <div className="w-full max-w-md">
                <BannerErro
                  mensagem="Não foi possível carregar o comprovante."
                  onRetry={onTentarNovamente}
                />
              </div>
            ) : comprovanteStatus === "loading" || comprovante === null ? (
              <p className="text-sm text-text-muted">Carregando…</p>
            ) : isMinioUrl ? (
              <p className="text-sm text-text-muted">
                Comprovante não disponível em ambiente de desenvolvimento
              </p>
            ) : isImage ? (
              <img
                src={comprovante.url}
                alt={pix?.nome_arquivo ?? "Comprovante"}
                className="max-h-full max-w-full object-contain"
              />
            ) : isPdf ? (
              <div className="flex h-full flex-col items-center gap-4" style={{ width: "90vw" }}>
                <iframe
                  src={comprovante.url}
                  title={pix?.nome_arquivo ?? "Comprovante"}
                  className="h-full w-full"
                />
                <a
                  href={comprovante.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-text-link underline-offset-4 hover:underline"
                >
                  <ExternalLink size={16} strokeWidth={1.5} />
                  Abrir em nova aba
                </a>
              </div>
            ) : (
              <a
                href={comprovante.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-text-link underline-offset-4 hover:underline"
              >
                <ExternalLink size={16} strokeWidth={1.5} />
                Abrir em nova aba
              </a>
            )}
          </div>
        </div>

        {/* Barra de ações — só para Pix pendente */}
        {hasActions && (
          <div className="flex-none border-t border-border bg-ink-0/95">
            {fase === "view" ? (
              <div className="flex gap-3 p-4">
                <Button
                  className="h-12 flex-1 bg-green-600 text-white hover:bg-green-500"
                  onClick={handleAprovar}
                  disabled={submitting}
                >
                  {submitting ? "Validando…" : "Validar Pix"}
                </Button>
                <Button
                  className="h-12 flex-1 bg-red-700 text-white hover:bg-red-600"
                  onClick={() => setFase("rejecting")}
                  disabled={submitting}
                >
                  Rejeitar Pix
                </Button>
              </div>
            ) : (
              <div className="space-y-3 p-4">
                <select
                  value={motivo}
                  onChange={(e) => {
                    setMotivo(e.target.value as MotivoRejeicao)
                    setErro(null)
                  }}
                  className="h-9 w-full rounded-lg border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  {motivoRejeicaoOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {motivo === "outro" && (
                  <Textarea
                    value={observacao}
                    onChange={(e) => {
                      setObservacao(e.target.value)
                      setErro(null)
                    }}
                    placeholder="Motivo interno (não exibido ao cliente)"
                    rows={2}
                    maxLength={500}
                  />
                )}
                {erro && <p className="text-[13px] text-danger-500">{erro}</p>}
                <div className="flex gap-3">
                  <Button
                    variant="secondary"
                    className="flex-1"
                    onClick={() => {
                      setFase("view")
                      setErro(null)
                    }}
                    disabled={submitting}
                  >
                    Cancelar
                  </Button>
                  <Button
                    className="h-10 flex-1 bg-red-700 text-white hover:bg-red-600"
                    onClick={handleRejeitar}
                    disabled={submitting}
                  >
                    {submitting ? "Rejeitando…" : "Confirmar rejeição"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
