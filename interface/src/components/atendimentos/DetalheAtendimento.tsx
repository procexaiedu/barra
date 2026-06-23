"use client"

import { useRef, useMemo, useState } from "react"
import Link from "next/link"
import { Clock, CreditCard, FileText, ImageOff, MessageSquare, Paperclip, Pencil, Plus, Trash2 } from "lucide-react"
import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
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
import { ehTelefoneExibivel, formatBRL, formatData, formatDataHora, formatTelefone, formatTempoRelativo, nomeCliente } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, EventoAtendimento, MotivoPerda } from "@/tipos/atendimentos"
import { AcoesAtendimento } from "@/components/atendimentos/AcoesAtendimento"
import { HistoricoMensagens } from "@/components/atendimentos/HistoricoMensagens"
import { LinhaEvento } from "@/components/atendimentos/LinhaEvento"
import { ResumoAtendimento } from "@/components/atendimentos/ResumoAtendimento"
import { badgeForEstado, categoriaEvento, corEstado, estadoLabel } from "@/components/atendimentos/utils"
import { ImageLightbox } from "@/components/ui/image-lightbox"

interface MidiaItem {
  id: string
  tipo: "imagem" | "audio" | "texto"
  origem: "interna" | "pix" | "recebida"
  nome: string
  subtitulo: string
  url: string | null
  pode_deletar: boolean
}

function getTipoDoArquivo(file: File): string {
  if (file.type.startsWith("image/")) return "imagem"
  if (file.type.startsWith("audio/")) return "audio"
  return "documento"
}

export function DetalheAtendimento({
  detalhe,
  status,
  error,
  onRetry,
  onDevolver,
  onFechar,
  onPerder,
  onUploadMidia,
  onDeletarMidia,
  onEditar,
  onCorrigir,
  readOnly = false,
}: {
  detalhe: AtendimentoDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onDevolver?: (id: string) => Promise<void>
  onFechar?: (id: string, valorFinal: number) => Promise<void>
  onPerder?: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onUploadMidia?: (atendimentoId: string, file: File, tipo: string) => Promise<void>
  onDeletarMidia?: (atendimentoId: string, midiaId: string) => Promise<void>
  onEditar?: () => void
  onCorrigir?: () => void
  readOnly?: boolean
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const atendimento = detalhe.atendimento
  const cliente = nomeCliente(detalhe.cliente.nome, detalhe.cliente.telefone)
  const telefoneExibivel = ehTelefoneExibivel(detalhe.cliente.telefone)
  const valorAcordado = atendimento.valor_acordado !== null && atendimento.valor_acordado !== undefined
    ? Number(atendimento.valor_acordado)
    : null
  const valorFinal = atendimento.estado === "Fechado" && atendimento.valor_final !== null
    ? Number(atendimento.valor_final)
    : null
  const valorExibido = valorFinal ?? (Number.isFinite(valorAcordado as number) ? valorAcordado : null)
  const valorLabel = valorFinal !== null ? "Valor final" : "Valor acordado"
  const valorColor = valorFinal !== null ? "text-success-500" : "text-gold-500"
  // Faixa de acento concorda com o badge de estado (mesma cor). A pausa da IA é
  // sinalizada pelo banner de handoff no resumo, não pela faixa.
  const estadoBorder = corEstado(atendimento.estado).faixa

  const totalMidias =
    detalhe.midias_internas.length +
    detalhe.comprovantes_pix.length +
    detalhe.mensagens.filter((m) => m.media_object_key).length

  return (
    <section aria-label="Detalhe do atendimento" className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
      <div className={cn("shrink-0 rounded-lg border-l-4 bg-card p-5 shadow-elev-1 ring-1 ring-border-subtle", estadoBorder)}>
        <div className="flex items-start gap-3">
          <Badge variant={badgeForEstado(atendimento.estado)} className="px-2.5 py-1 text-[12px]">
            {estadoLabel[atendimento.estado]}
          </Badge>
          <span className="ml-auto flex shrink-0 items-center gap-2 text-[12px] font-medium text-text-muted">
            <span>#{atendimento.numero_curto}</span>
            <span aria-hidden>·</span>
            <span>{formatTempoRelativo(atendimento.updated_at)}</span>
            {onEditar && (
              <button
                type="button"
                onClick={onEditar}
                title="Editar atendimento"
                aria-label="Editar atendimento"
                className="ml-1 rounded p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Pencil size={14} strokeWidth={1.5} aria-hidden />
              </button>
            )}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold leading-tight tracking-tight text-text-primary">
              {cliente}
            </h2>
            <p className="mt-1 text-[13px] text-text-muted">
              Atendimento de <span className="font-medium text-text-secondary">{detalhe.modelo.nome}</span>
              {telefoneExibivel && (
                <>
                  <span aria-hidden> · </span>
                  <span className="font-mono text-text-muted">{formatTelefone(detalhe.cliente.telefone)}</span>
                </>
              )}
            </p>
          </div>
          {valorExibido !== null && (
            <div className="text-right">
              <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">{valorLabel}</p>
              <p className={cn("font-mono text-2xl font-semibold leading-none tabular-nums", valorColor)}>
                {formatBRL(valorExibido)}
              </p>
            </div>
          )}
        </div>

        {!readOnly && onDevolver && onFechar && onPerder && (
          <div className="mt-4">
            <AcoesAtendimento
              atendimento={atendimento}
              onDevolver={onDevolver}
              onFechar={onFechar}
              onPerder={onPerder}
            />
          </div>
        )}

        {!readOnly && onCorrigir && (atendimento.estado === "Fechado" || atendimento.estado === "Perdido") && (
          <div className="mt-4">
            <Button variant="secondary" size="sm" onClick={onCorrigir}>
              Corrigir resultado
            </Button>
          </div>
        )}
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid grid-cols-[1.4fr_1fr] items-start gap-3">
          <div className="flex min-w-0 flex-col gap-3">
            <ResumoAtendimento detalhe={detalhe} />
            <SecaoFixa
              titulo="Conversa com o cliente"
              count={detalhe.mensagens.length}
              icone={<MessageSquare size={16} strokeWidth={1.75} className="text-info-500" />}
            >
              <HistoricoMensagens mensagens={detalhe.mensagens} />
            </SecaoFixa>
          </div>
          <div className="flex min-w-0 flex-col gap-3">
            <SecaoFixa
              titulo="Mídias recebidas"
              count={totalMidias}
              icone={<Paperclip size={16} strokeWidth={1.75} className="text-gold-500" />}
            >
              <MidiasRecebidas
                detalhe={detalhe}
                onUploadMidia={onUploadMidia}
                onDeletarMidia={onDeletarMidia}
                readOnly={readOnly}
              />
            </SecaoFixa>
            <SecaoFixa
              titulo="Linha do tempo"
              count={detalhe.eventos.length}
              icone={<Clock size={16} strokeWidth={1.75} className="text-text-muted" />}
            >
              <Eventos eventos={detalhe.eventos} />
            </SecaoFixa>
          </div>
        </div>
      </div>
    </section>
  )
}

function SecaoFixa({
  titulo,
  count,
  icone,
  children,
}: {
  titulo: string
  count?: number
  icone?: ReactNode
  children: ReactNode
}) {
  const temContagem = count !== undefined && count > 0
  return (
    <div className="flex flex-col overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle">
      <div className="flex shrink-0 items-center gap-2.5 px-4 py-3">
        {icone && <span className="shrink-0">{icone}</span>}
        <span className="flex-1 text-base font-semibold text-text-primary">{titulo}</span>
        {temContagem && (
          <span className="inline-flex min-w-[22px] items-center justify-center rounded-full bg-accent px-2 py-0.5 font-mono text-xs font-semibold tabular-nums text-text-secondary">
            {count}
          </span>
        )}
      </div>
      <div className="border-t border-border p-4">
        {children}
      </div>
    </div>
  )
}

function MidiasRecebidas({
  detalhe,
  onUploadMidia,
  onDeletarMidia,
  readOnly = false,
}: {
  detalhe: AtendimentoDetalheResponse
  onUploadMidia?: (atendimentoId: string, file: File, tipo: string) => Promise<void>
  onDeletarMidia?: (atendimentoId: string, midiaId: string) => Promise<void>
  readOnly?: boolean
}) {
  const [midiaAberta, setMidiaAberta] = useState<MidiaItem | null>(null)
  const [midiaParaDeletar, setMidiaParaDeletar] = useState<MidiaItem | null>(null)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const midias = useMemo<MidiaItem[]>(() => {
    const internas = detalhe.midias_internas.map((midia) => ({
      id: midia.id,
      tipo: (midia.tipo === "documento" ? "texto" : midia.tipo) as "imagem" | "audio" | "texto",
      origem: "interna" as const,
      nome: midia.nome_arquivo,
      subtitulo: `${midia.tipo} · ${formatDataHora(midia.created_at)}`,
      url: midia.media_url ?? null,
      pode_deletar: true,
    }))
    const pix = detalhe.comprovantes_pix.map((comprovante) => ({
      id: comprovante.id,
      tipo: "imagem" as const,
      origem: "pix" as const,
      nome: "comprovante Pix",
      subtitulo: `${comprovante.decisao_pipeline} · ${formatDataHora(comprovante.created_at)}`,
      url: null,
      pode_deletar: false,
    }))
    const recebidas = detalhe.mensagens
      .filter((mensagem) => mensagem.media_object_key)
      .map((mensagem) => ({
        id: mensagem.id,
        tipo: mensagem.tipo as "imagem" | "audio" | "texto",
        origem: "recebida" as const,
        nome: mensagem.media_object_key?.split("/").pop() ?? mensagem.tipo,
        subtitulo: `${mensagem.tipo} · ${formatDataHora(mensagem.created_at)}`,
        url: mensagem.media_url ?? null,
        pode_deletar: false,
      }))
    return [...internas, ...pix, ...recebidas]
  }, [detalhe])

  async function handleArquivoSelecionado(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !onUploadMidia) return
    e.target.value = ""
    setUploadLoading(true)
    try {
      await onUploadMidia(detalhe.atendimento.id, file, getTipoDoArquivo(file))
    } finally {
      setUploadLoading(false)
    }
  }

  async function handleConfirmarDelete() {
    if (!midiaParaDeletar || !onDeletarMidia) return
    setDeleteLoading(true)
    try {
      await onDeletarMidia(detalhe.atendimento.id, midiaParaDeletar.id)
      setMidiaParaDeletar(null)
    } finally {
      setDeleteLoading(false)
    }
  }

  return (
    <>
      {midias.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2.5 py-6 text-center">
          <div className="flex size-10 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
            <ImageOff size={18} strokeWidth={1.75} className="text-text-muted" />
          </div>
          <p className="text-[13px] text-text-secondary">Nenhuma mídia recebida neste atendimento.</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {midias.map((midia) => {
            if (!midia.pode_deletar && midia.url === null) {
              const ehPix = midia.origem === "pix"
              return (
                <Link
                  key={midia.id}
                  href="/pix"
                  className={cn(
                    "inline-flex max-w-full items-center gap-2 rounded-md px-3 py-2 font-mono text-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    ehPix
                      ? "bg-gold-500/10 text-gold-500 hover:bg-gold-500/15"
                      : "bg-accent text-text-muted hover:bg-muted hover:text-text-primary"
                  )}
                >
                  {ehPix
                    ? <CreditCard size={14} strokeWidth={1.5} />
                    : <FileText size={14} strokeWidth={1.5} />}
                  <span className="truncate">{midia.nome}</span>
                  <span className="font-sans text-text-disabled">{midia.subtitulo}</span>
                </Link>
              )
            }
            return (
              <div key={midia.id} className="group relative inline-flex">
                <button
                  type="button"
                  onClick={() => midia.url && setMidiaAberta(midia)}
                  disabled={!midia.url}
                  className="inline-flex max-w-full items-center gap-2 rounded-md bg-accent px-3 py-2 font-mono text-xs text-text-muted outline-none transition-colors enabled:hover:bg-muted enabled:hover:text-text-primary disabled:cursor-default focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <FileText size={14} strokeWidth={1.5} />
                  <span className="truncate">{midia.nome}</span>
                  <span className="font-sans text-text-disabled">{midia.subtitulo}</span>
                </button>
                {midia.pode_deletar && !readOnly && (
                  <button
                    type="button"
                    onClick={() => setMidiaParaDeletar(midia)}
                    aria-label="Remover mídia"
                    className="absolute -right-2 -top-2 hidden rounded-full bg-border-strong p-0.5 text-text-muted transition-colors hover:bg-destructive hover:text-text-inverse group-hover:flex"
                  >
                    <Trash2 size={11} strokeWidth={2} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {!readOnly && onUploadMidia && (
        <div className="mt-3">
          <input
            ref={inputRef}
            type="file"
            accept="image/*,audio/*,application/pdf"
            className="hidden"
            onChange={handleArquivoSelecionado}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploadLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:bg-accent hover:text-text-primary disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Plus size={13} strokeWidth={2} />
            {uploadLoading ? "Enviando..." : "Adicionar mídia"}
          </button>
        </div>
      )}

      {/* Viewer */}
      {midiaAberta?.url && midiaAberta.tipo === "audio" && (
        <AlertDialog open={!!midiaAberta} onOpenChange={(open) => !open && setMidiaAberta(null)}>
          <AlertDialogContent className="max-w-4xl rounded-none bg-popover p-0">
            <AlertDialogTitle className="sr-only">{midiaAberta.nome}</AlertDialogTitle>
            <audio controls src={midiaAberta.url} className="w-full p-4" />
          </AlertDialogContent>
        </AlertDialog>
      )}
      <ImageLightbox
        open={!!midiaAberta && midiaAberta.tipo !== "audio"}
        src={midiaAberta?.url ?? ""}
        alt={midiaAberta?.nome ?? "Imagem"}
        onClose={() => setMidiaAberta(null)}
      />

      {/* Confirmação de deleção */}
      <AlertDialog open={!!midiaParaDeletar} onOpenChange={(open) => !open && !deleteLoading && setMidiaParaDeletar(null)}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>Remover mídia?</AlertDialogTitle>
            <AlertDialogDescription>Esta ação não pode ser desfeita.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteLoading}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmarDelete} disabled={deleteLoading}>
              {deleteLoading ? "Removendo..." : "Remover"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function Eventos({ eventos }: { eventos: AtendimentoDetalheResponse["eventos"] }) {
  const [mostrarTelemetria, setMostrarTelemetria] = useState(false)

  const ordenados = useMemo(
    () => [...eventos].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [eventos]
  )
  const telemetriaCount = useMemo(
    () => ordenados.filter((e) => categoriaEvento(e.tipo) === "telemetria").length,
    [ordenados]
  )
  const visiveis = useMemo(
    () => (mostrarTelemetria ? ordenados : ordenados.filter((e) => categoriaEvento(e.tipo) === "marco")),
    [ordenados, mostrarTelemetria]
  )
  // Agrupa por dia (já vem em ordem decrescente) — cabeçalho de data por grupo,
  // só a hora em cada item.
  const grupos = useMemo(() => {
    const mapa = new Map<string, EventoAtendimento[]>()
    for (const ev of visiveis) {
      const dia = formatData(ev.created_at)
      const lista = mapa.get(dia) ?? []
      lista.push(ev)
      mapa.set(dia, lista)
    }
    return [...mapa.entries()]
  }, [visiveis])

  if (ordenados.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2.5 py-6 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
          <Clock size={18} strokeWidth={1.75} className="text-text-muted" />
        </div>
        <p className="text-[13px] text-text-secondary">Nenhum evento registrado neste atendimento.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {grupos.map(([dia, evs]) => (
        <div key={dia}>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">{dia}</p>
          <ol className="flex flex-col">
            {evs.map((evento, i) => (
              <LinhaEvento key={evento.id} evento={evento} isLast={i === evs.length - 1} />
            ))}
          </ol>
        </div>
      ))}
      {visiveis.length === 0 && (
        <p className="text-[13px] text-text-disabled">Sem marcos ainda — só atualizações internas da IA.</p>
      )}
      {telemetriaCount > 0 && (
        <button
          type="button"
          onClick={() => setMostrarTelemetria((v) => !v)}
          className="self-start text-[12px] font-medium text-text-link hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {mostrarTelemetria
            ? "Ocultar atualizações da IA"
            : `Mostrar atualizações da IA (${telemetriaCount})`}
        </button>
      )}
    </div>
  )
}

function EmptyDetalhe() {
  return (
    <section
      aria-label="Detalhe do atendimento"
      className="flex min-h-[320px] flex-1 flex-col items-center justify-center gap-3 rounded-lg bg-card p-6 text-center shadow-elev-1 ring-1 ring-border-subtle"
    >
      <div className="flex size-12 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
        <MessageSquare size={24} strokeWidth={1.5} className="text-text-muted" />
      </div>
      <div>
        <p className="text-sm font-medium text-text-primary">Nenhum atendimento selecionado.</p>
        <p className="mt-1 text-[13px] text-text-muted">Selecione um item da lista para ver o contexto completo.</p>
      </div>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe do atendimento" aria-busy="true" className="space-y-3">
      {/* Card header: badge + nome + telefone + botões */}
      <div className="rounded-lg bg-card p-5 shadow-elev-1 ring-1 ring-border-subtle">
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton className="h-5 w-28 rounded-full" />
          <Skeleton className="h-5 w-40 rounded" />
          <Skeleton className="ml-auto h-4 w-24 rounded" />
        </div>
        <Skeleton className="mt-2 h-4 w-36 rounded" />
        <div className="mt-3 flex gap-2">
          <Skeleton className="h-8 w-36 rounded-lg" />
          <Skeleton className="h-8 w-24 rounded-lg" />
          <Skeleton className="h-8 w-20 rounded-lg" />
        </div>
      </div>
      {/* Resumo */}
      <div className="rounded-lg bg-card p-4 shadow-elev-1 ring-1 ring-border-subtle">
        <Skeleton className="mb-4 h-4 w-44 rounded" />
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-2">
            <Skeleton className="mb-3 h-3 w-20 rounded" />
            {[72, 90, 60, 80, 100].map((w, i) => (
              <Skeleton key={i} className="h-3 rounded" style={{ width: w }} />
            ))}
          </div>
          <div className="space-y-2">
            <Skeleton className="mb-3 h-3 w-24 rounded" />
            {[80, 96, 64, 80, 112, 72].map((w, i) => (
              <Skeleton key={i} className="h-3 rounded" style={{ width: w }} />
            ))}
          </div>
        </div>
      </div>
      {/* Seções colapsadas */}
      {["Histórico de mensagens", "Mídias recebidas", "Histórico do atendimento"].map((titulo) => (
        <div key={titulo} className="overflow-hidden rounded-lg bg-card shadow-elev-1 ring-1 ring-border-subtle">
          <div className="flex items-center justify-between px-4 py-3">
            <Skeleton className="h-4 w-44 rounded" />
            <Skeleton className="h-4 w-4 rounded" />
          </div>
        </div>
      ))}
    </section>
  )
}
