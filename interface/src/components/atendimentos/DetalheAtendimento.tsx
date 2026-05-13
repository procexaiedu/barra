"use client"

import { useRef, useMemo, useState } from "react"
import Link from "next/link"
import { ChevronDown, Clock, FileText, ImageOff, MessageSquare, Paperclip, Pencil, Plus, Trash2 } from "lucide-react"
import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
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
import { formatBRL, formatDataHora, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, MotivoPerda } from "@/tipos/atendimentos"
import { AcoesAtendimento } from "@/components/atendimentos/AcoesAtendimento"
import { HistoricoMensagens } from "@/components/atendimentos/HistoricoMensagens"
import { LinhaEvento } from "@/components/atendimentos/LinhaEvento"
import { ResumoAtendimento } from "@/components/atendimentos/ResumoAtendimento"
import { badgeForEstado, estadoLabel } from "@/components/atendimentos/utils"
import { ImageLightbox } from "@/components/ui/image-lightbox"

interface MidiaItem {
  id: string
  tipo: "imagem" | "audio" | "texto"
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
}: {
  detalhe: AtendimentoDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onUploadMidia: (atendimentoId: string, file: File, tipo: string) => Promise<void>
  onDeletarMidia: (atendimentoId: string, midiaId: string) => Promise<void>
  onEditar?: () => void
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const atendimento = detalhe.atendimento
  const cliente = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const valorAcordado = atendimento.valor_acordado !== null && atendimento.valor_acordado !== undefined
    ? Number(atendimento.valor_acordado)
    : null
  const valorFinal = atendimento.estado === "Fechado" && atendimento.valor_final !== null
    ? Number(atendimento.valor_final)
    : null
  const valorExibido = valorFinal ?? (Number.isFinite(valorAcordado as number) ? valorAcordado : null)
  const valorLabel = valorFinal !== null ? "Valor final" : "Valor acordado"
  const valorColor = valorFinal !== null ? "text-success-500" : "text-gold-500"
  const estadoBorder =
    atendimento.estado === "Fechado" ? "border-l-state-closed" :
    atendimento.estado === "Perdido" ? "border-l-state-lost" :
    atendimento.ia_pausada ? "border-l-state-handoff" :
    "border-l-state-active"

  return (
    <section aria-label="Detalhe do atendimento" className="min-w-0 space-y-3">
      <div className={cn("rounded-lg border border-ink-300 bg-ink-200 p-5 border-l-4", estadoBorder)}>
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
                className="ml-1 rounded p-1 text-text-muted transition-colors hover:bg-ink-300 hover:text-text-primary"
              >
                <Pencil size={14} strokeWidth={1.5} />
              </button>
            )}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-[28px] font-medium leading-tight tracking-tight text-text-primary">
              {cliente}
            </h2>
            <p className="mt-1 text-[13px] text-text-muted">
              Atendimento de <span className="font-medium text-text-secondary">{detalhe.modelo.nome}</span>
              <span aria-hidden> · </span>
              <span className="font-mono text-text-muted">{formatTelefone(detalhe.cliente.telefone)}</span>
            </p>
          </div>
          {valorExibido !== null && (
            <div className="text-right">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">{valorLabel}</p>
              <p className={cn("font-serif text-[28px] font-medium leading-none tabular-nums", valorColor)}>
                {formatBRL(valorExibido)}
              </p>
            </div>
          )}
        </div>

        <div className="mt-4">
          <AcoesAtendimento
            atendimento={atendimento}
            onDevolver={onDevolver}
            onFechar={onFechar}
            onPerder={onPerder}
          />
        </div>
      </div>

      <ResumoAtendimento detalhe={detalhe} />

      <SecaoColapsavel
        titulo="Histórico de mensagens"
        count={detalhe.mensagens.length}
        defaultOpen={atendimento.ia_pausada}
        icone={<MessageSquare size={16} strokeWidth={1.75} className="text-info-500" />}
      >
        <HistoricoMensagens mensagens={detalhe.mensagens} />
      </SecaoColapsavel>

      <SecaoColapsavel
        titulo="Mídias recebidas"
        count={detalhe.midias_internas.length + detalhe.comprovantes_pix.length + detalhe.mensagens.filter(m => m.media_object_key).length}
        icone={<Paperclip size={16} strokeWidth={1.75} className="text-gold-500" />}
      >
        <MidiasRecebidas
          detalhe={detalhe}
          onUploadMidia={onUploadMidia}
          onDeletarMidia={onDeletarMidia}
        />
      </SecaoColapsavel>

      <SecaoColapsavel
        titulo="Histórico do atendimento"
        count={detalhe.eventos.length}
        icone={<Clock size={16} strokeWidth={1.75} className="text-text-muted" />}
      >
        <Eventos eventos={detalhe.eventos} />
      </SecaoColapsavel>
    </section>
  )
}

function SecaoColapsavel({
  titulo,
  count,
  defaultOpen,
  icone,
  children,
}: {
  titulo: string
  count?: number
  defaultOpen?: boolean
  icone?: ReactNode
  children: ReactNode
}) {
  const [aberto, setAberto] = useState(defaultOpen ?? false)
  const temContagem = count !== undefined && count > 0
  return (
    <div className="overflow-hidden rounded-lg border border-ink-300 bg-ink-100">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        className="flex w-full items-center gap-2.5 px-4 py-3.5 text-left transition-colors hover:bg-ink-200"
      >
        {icone && <span className="shrink-0">{icone}</span>}
        <span className="flex-1 text-[15px] font-semibold text-text-primary">{titulo}</span>
        {temContagem && (
          <span className="inline-flex min-w-[22px] items-center justify-center rounded-full bg-ink-300 px-2 py-0.5 text-[12px] font-semibold tabular-nums text-text-secondary">
            {count}
          </span>
        )}
        <ChevronDown
          size={18}
          strokeWidth={1.75}
          className={cn("text-text-muted transition-transform duration-150", aberto && "rotate-180")}
        />
      </button>
      {aberto && (
        <div className="border-t border-ink-300 p-4">
          {children}
        </div>
      )}
    </div>
  )
}

function MidiasRecebidas({
  detalhe,
  onUploadMidia,
  onDeletarMidia,
}: {
  detalhe: AtendimentoDetalheResponse
  onUploadMidia: (atendimentoId: string, file: File, tipo: string) => Promise<void>
  onDeletarMidia: (atendimentoId: string, midiaId: string) => Promise<void>
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
      nome: midia.nome_arquivo,
      subtitulo: `${midia.tipo} · ${formatDataHora(midia.created_at)}`,
      url: midia.media_url ?? null,
      pode_deletar: true,
    }))
    const pix = detalhe.comprovantes_pix.map((comprovante) => ({
      id: comprovante.id,
      tipo: "imagem" as const,
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
        nome: mensagem.media_object_key?.split("/").pop() ?? mensagem.tipo,
        subtitulo: `${mensagem.tipo} · ${formatDataHora(mensagem.created_at)}`,
        url: mensagem.media_url ?? null,
        pode_deletar: false,
      }))
    return [...internas, ...pix, ...recebidas]
  }, [detalhe])

  async function handleArquivoSelecionado(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ""
    setUploadLoading(true)
    try {
      await onUploadMidia(detalhe.atendimento.id, file, getTipoDoArquivo(file))
    } finally {
      setUploadLoading(false)
    }
  }

  async function handleConfirmarDelete() {
    if (!midiaParaDeletar) return
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
        <div className="flex items-start gap-3">
          <ImageOff size={20} strokeWidth={1.5} className="mt-0.5 text-text-muted" />
          <p className="text-sm text-text-primary">Nenhuma mídia recebida neste atendimento.</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {midias.map((midia) => {
            if (!midia.pode_deletar && midia.url === null) {
              return (
                <Link
                  key={midia.id}
                  href="/pix"
                  className="inline-flex max-w-full items-center gap-2 rounded-md bg-ink-300 px-3 py-2 font-mono text-xs text-text-muted outline-none transition-colors hover:bg-ink-200 hover:text-text-primary focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
                >
                  <FileText size={14} strokeWidth={1.5} />
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
                  className="inline-flex max-w-full items-center gap-2 rounded-md bg-ink-300 px-3 py-2 font-mono text-xs text-text-muted outline-none transition-colors enabled:hover:bg-ink-200 enabled:hover:text-text-primary disabled:cursor-default focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
                >
                  <FileText size={14} strokeWidth={1.5} />
                  <span className="truncate">{midia.nome}</span>
                  <span className="font-sans text-text-disabled">{midia.subtitulo}</span>
                </button>
                {midia.pode_deletar && (
                  <button
                    type="button"
                    onClick={() => setMidiaParaDeletar(midia)}
                    aria-label="Remover mídia"
                    className="absolute -right-2 -top-2 hidden rounded-full bg-ink-400 p-0.5 text-text-muted transition-colors hover:bg-red-500 hover:text-white group-hover:flex"
                  >
                    <Trash2 size={11} strokeWidth={2} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

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
          className="inline-flex items-center gap-1.5 rounded-md border border-ink-300 bg-ink-100 px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:bg-ink-200 hover:text-text-primary disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
        >
          <Plus size={13} strokeWidth={2} />
          {uploadLoading ? "Enviando..." : "Adicionar mídia"}
        </button>
      </div>

      {/* Viewer */}
      {midiaAberta?.url && midiaAberta.tipo === "audio" && (
        <AlertDialog open={!!midiaAberta} onOpenChange={(open) => !open && setMidiaAberta(null)}>
          <AlertDialogContent className="max-w-4xl rounded-none bg-ink-0 p-0">
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
  const ordenados = useMemo(
    () => [...eventos].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
    [eventos]
  )

  if (ordenados.length === 0) {
    return <p className="text-sm text-text-primary">Nenhum evento registrado neste atendimento.</p>
  }

  return (
    <div>
      {ordenados.map((evento) => (
        <LinhaEvento key={evento.id} evento={evento} />
      ))}
    </div>
  )
}

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe do atendimento" className="rounded-lg border border-ink-300 bg-ink-100 p-6">
      <p className="text-sm text-text-primary">Nenhum atendimento selecionado.</p>
      <p className="mt-1 text-[13px] text-text-muted">Selecione um item da lista para ver o contexto completo.</p>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe do atendimento" aria-busy="true" className="space-y-3">
      {/* Card header: badge + nome + telefone + botões */}
      <div className="rounded-lg border border-ink-300 bg-ink-100 p-4">
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
      <div className="rounded-lg border border-ink-300 bg-ink-100 p-4">
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
        <div key={titulo} className="overflow-hidden rounded-lg border border-ink-300 bg-ink-100">
          <div className="flex items-center justify-between px-4 py-3">
            <Skeleton className="h-4 w-44 rounded" />
            <Skeleton className="h-4 w-4 rounded" />
          </div>
        </div>
      ))}
    </section>
  )
}
