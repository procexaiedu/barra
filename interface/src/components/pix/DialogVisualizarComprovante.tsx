"use client"

import { useState } from "react"
import {
  CheckCircle2,
  ExternalLink,
  FileText,
  RotateCcw,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogCloseButton,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { BannerErro } from "@/components/layout/BannerErro"
import { formatBRL, formatDataHora, formatTelefone } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type {
  ChecagemPix,
  ClienteResumoPix,
  ComprovanteUrlResponse,
  ModeloResumoPix,
  MotivoRejeicao,
  PixDetalhe,
} from "@/tipos/pix"
import {
  badgeForStatusPix,
  checagemLabel,
  motivoRejeicaoOptions,
  motivoRevisaoLabel,
  statusItemPix,
  tipoChaveLabel,
} from "./utils"

type Fase = "view" | "rejecting"

export function DialogVisualizarComprovante({
  open,
  onOpenChange,
  pix,
  cliente,
  modelo,
  checagens,
  comprovante,
  comprovanteStatus,
  onTentarNovamente,
  onAprovar,
  onRejeitar,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  pix: PixDetalhe | null
  cliente: ClienteResumoPix | null
  modelo: ModeloResumoPix | null
  checagens: ChecagemPix[]
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
  const [imgErro, setImgErro] = useState(false)
  const [openAnterior, setOpenAnterior] = useState(open)
  const [urlAnterior, setUrlAnterior] = useState(comprovante?.url ?? null)

  if (open !== openAnterior) {
    setOpenAnterior(open)
    if (!open) {
      setFase("view")
      setMotivo("valor_incorreto")
      setObservacao("")
      setErro(null)
    }
  }

  // Nova URL (ex.: após recarregar um link expirado) zera o estado de erro da imagem.
  if ((comprovante?.url ?? null) !== urlAnterior) {
    setUrlAnterior(comprovante?.url ?? null)
    setImgErro(false)
  }

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

  const status = pix ? statusItemPix(pix.decisao_pipeline, pix.decisao_final) : null
  const badge = status ? badgeForStatusPix(status) : null
  const valor = pix?.valor_extraido !== null && pix?.valor_extraido !== undefined
    ? formatBRL(pix.valor_extraido)
    : null
  const horario = pix?.horario_transacao ? formatDataHora(pix.horario_transacao) : null
  const clienteLabel = cliente
    ? cliente.nome ?? formatTelefone(cliente.telefone)
    : null
  const motivoRevisao =
    pix?.motivo_em_revisao && pix.motivo_em_revisao in motivoRevisaoLabel
      ? motivoRevisaoLabel[pix.motivo_em_revisao]
      : null

  const totalChecagens = checagens.length
  const passaram = checagens.filter((c) => c.passou).length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="xl"
        className="h-[min(96vh,68rem)] max-h-none w-[min(98vw,108rem)] overflow-hidden"
      >
        {/* Header */}
        <DialogHeader className="justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <DialogTitle className="text-lg font-semibold text-text-primary">
              Comprovante Pix
            </DialogTitle>
            {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
            {clienteLabel && (
              <span className="truncate text-sm text-text-secondary">
                · {clienteLabel}
              </span>
            )}
            {modelo && (
              <span className="hidden truncate text-xs text-text-muted md:inline">
                em conversa com {modelo.nome}
              </span>
            )}
          </div>
          <DialogCloseButton />
        </DialogHeader>

        {/* Body: viewer + sidebar */}
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_440px]">
          {/* Viewer */}
          <div
            className="relative flex min-h-0 items-center justify-center overflow-hidden bg-ink-0"
            onClick={() => !submitting && onOpenChange(false)}
          >
            <div
              className="flex max-h-full max-w-full flex-col items-center justify-center px-6 py-6"
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
                imgErro ? (
                  <div className="w-full max-w-md text-center">
                    <BannerErro
                      mensagem="Não foi possível exibir a imagem do comprovante. O link pode ter expirado."
                      onRetry={onTentarNovamente}
                    />
                    <a
                      href={comprovante.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-3 inline-flex items-center gap-2 text-xs text-text-link underline-offset-4 hover:underline"
                    >
                      <ExternalLink size={14} strokeWidth={1.5} />
                      Abrir em nova aba
                    </a>
                  </div>
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={comprovante.url}
                    alt={pix?.nome_arquivo ?? "Comprovante"}
                    onError={() => setImgErro(true)}
                    className="max-h-full max-w-full rounded-md object-contain shadow-lg"
                  />
                )
              ) : isPdf ? (
                <div className="flex h-full w-full flex-col items-center gap-3">
                  <iframe
                    src={comprovante.url}
                    title={pix?.nome_arquivo ?? "Comprovante"}
                    className="h-full w-full rounded-md bg-white"
                  />
                  <a
                    href={comprovante.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 text-xs text-text-link underline-offset-4 hover:underline"
                  >
                    <ExternalLink size={14} strokeWidth={1.5} />
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
                  <FileText size={16} strokeWidth={1.5} />
                  Abrir comprovante em nova aba
                </a>
              )}
            </div>
          </div>

          {/* Sidebar */}
          <aside className="flex min-h-0 flex-col overflow-y-auto border-l border-border bg-card">
            {/* Hero: valor */}
            <div className="border-b border-border px-6 py-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Valor extraído
              </p>
              <p
                className={cn(
                  "mt-1 font-mono font-semibold leading-none tabular-nums",
                  valor ? "text-[40px] text-text-primary" : "text-2xl text-text-muted",
                )}
              >
                {valor ?? "Não identificado"}
              </p>
              {motivoRevisao && (
                <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-state-handoff/15 px-2.5 py-1 text-xs font-medium text-state-handoff">
                  <RotateCcw size={12} strokeWidth={1.8} />
                  {motivoRevisao}
                </p>
              )}
            </div>

            {fase === "view" ? (
              <>
                {/* Dados do comprovante */}
                <section className="border-b border-border px-6 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                    Dados do comprovante
                  </p>
                  <dl className="mt-3 space-y-2.5 text-sm">
                    <Linha label="Remetente">
                      {pix?.titular_extraido ? (
                        <div className="space-y-0.5">
                          <p className="break-words text-text-primary">{pix.titular_extraido}</p>
                          {pix.documento_extraido && (
                            <p className="break-all font-mono text-xs text-text-muted">
                              {pix.documento_extraido}
                            </p>
                          )}
                        </div>
                      ) : (
                        <NaoExtraido />
                      )}
                    </Linha>
                    <Linha label="Chave destino">
                      {pix?.chave_extraida ? (
                        <div className="space-y-0.5">
                          <p className="break-all font-mono text-[13px] text-text-primary">
                            {pix.chave_extraida}
                          </p>
                          {pix.tipo_chave && (
                            <p className="text-xs text-text-muted">
                              {tipoChaveLabel[pix.tipo_chave]}
                            </p>
                          )}
                        </div>
                      ) : (
                        <NaoExtraido />
                      )}
                    </Linha>
                    <Linha label="Data e hora">
                      {horario ? (
                        <span className="text-text-primary">{horario}</span>
                      ) : (
                        <NaoExtraido />
                      )}
                    </Linha>
                  </dl>
                </section>

                {/* Verificações */}
                {totalChecagens > 0 && (
                  <section className="border-b border-border px-6 py-4">
                    <div className="flex items-baseline justify-between">
                      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                        Verificações automáticas
                      </p>
                      <span className="text-xs text-text-muted">
                        {passaram}/{totalChecagens} passaram
                      </span>
                    </div>
                    <ul className="mt-3 space-y-2">
                      {checagens.map((c) => (
                        <li key={c.chave} className="flex items-start gap-2.5">
                          {c.passou ? (
                            <CheckCircle2
                              size={16}
                              strokeWidth={1.5}
                              className="mt-0.5 shrink-0 text-state-closed"
                              aria-label="passou"
                            />
                          ) : (
                            <XCircle
                              size={16}
                              strokeWidth={1.5}
                              className="mt-0.5 shrink-0 text-state-lost"
                              aria-label="falhou"
                            />
                          )}
                          <div className="min-w-0 flex-1">
                            <p
                              className={cn(
                                "text-[13px] leading-tight",
                                c.passou ? "text-text-secondary" : "text-text-primary",
                              )}
                            >
                              {checagemLabel(c)}
                            </p>
                            {!c.passou && c.motivo && (
                              <p className="mt-0.5 text-xs text-text-muted">{c.motivo}</p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            ) : (
              <section className="border-b border-border px-6 py-4">
                <div className="flex items-baseline justify-between">
                  <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                    Por que rejeitar?
                  </p>
                  <span className="text-xs text-text-muted">{observacao.length}/500</span>
                </div>
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
                        "flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors",
                        motivo === o.value
                          ? "border-danger-500/70 bg-danger-500/10 text-text-primary"
                          : "border-border bg-muted text-text-secondary hover:border-border-strong hover:text-text-primary",
                      )}
                    >
                      <span>{o.label}</span>
                      {motivo === o.value && (
                        <span
                          aria-hidden
                          className="size-2 rounded-full bg-danger-500"
                        />
                      )}
                    </button>
                  ))}
                </div>
                {motivo === "outro" && (
                  <div className="mt-3">
                    <Label htmlFor="dlg-comp-obs" className="text-xs text-text-muted">
                      Observação interna
                    </Label>
                    <Textarea
                      id="dlg-comp-obs"
                      value={observacao}
                      onChange={(e) => {
                        setObservacao(e.target.value)
                        setErro(null)
                      }}
                      placeholder="Motivo interno (não exibido ao cliente)"
                      rows={3}
                      maxLength={500}
                      className="mt-1.5"
                    />
                  </div>
                )}
                {erro && <p className="mt-2 text-[13px] text-danger-500">{erro}</p>}
              </section>
            )}
          </aside>
        </div>

        {/* Footer */}
        {hasActions && (
          <DialogFooter>
            {fase === "view" ? (
              <>
                <Button
                  variant="destructive"
                  onClick={() => setFase("rejecting")}
                  disabled={submitting}
                >
                  Rejeitar Pix
                </Button>
                <Button
                  className="bg-success-500 text-on-success hover:bg-success-500/90"
                  onClick={handleAprovar}
                  disabled={submitting}
                >
                  {submitting ? "Validando…" : "Validar Pix"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setFase("view")
                    setErro(null)
                  }}
                  disabled={submitting}
                >
                  Voltar
                </Button>
                <Button
                  variant="danger"
                  onClick={handleRejeitar}
                  disabled={submitting}
                >
                  {submitting ? "Rejeitando…" : "Confirmar rejeição"}
                </Button>
              </>
            )}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Linha({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] items-start gap-3">
      <dt className="pt-0.5 text-xs uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

function NaoExtraido() {
  return <span className="text-text-muted">Não identificado</span>
}
