"use client"

import { useRef, useMemo, useState } from "react"
import Image from "next/image"
import Link from "next/link"
import { ChevronDown, FileText, ImageOff, Plus, Trash2 } from "lucide-react"
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
}: {
  detalhe: AtendimentoDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
  onUploadMidia: (atendimentoId: string, file: File, tipo: string) => Promise<void>
  onDeletarMidia: (atendimentoId: string, mensagemId: string) => Promise<void>
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const atendimento = detalhe.atendimento
  const cliente = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const estadoBorder =
    atendimento.estado === "Fechado" ? "border-l-state-closed" :
    atendimento.estado === "Perdido" ? "border-l-state-lost" :
    atendimento.ia_pausada ? "border-l-state-handoff" :
    "border-l-state-active"

  return (
    <section aria-label="Detalhe do atendimento" className="min-w-0 space-y-3">
      <div className={cn("rounded-lg border border-ink-300 bg-ink-100 p-4 border-l-3", estadoBorder)}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={badgeForEstado(atendimento.estado)}>{estadoLabel[atendimento.estado]}</Badge>
          <h2 className="text-base font-semibold text-text-primary">{cliente}</h2>
          <span className="text-sm text-text-muted">· {detalhe.modelo.nome}</span>
          <span className="ml-auto text-xs font-medium text-text-muted">
            #{atendimento.numero_curto} · {formatTempoRelativo(atendimento.updated_at)}
          </span>
        </div>
        {atendimento.estado === "Fechado" && atendimento.valor_final !== null && (
          <div className="mt-1 flex items-center gap-1">
            <span className="text-xs text-text-muted">Valor final</span>
            <span className="ml-2 text-sm font-semibold text-success-500">{formatBRL(Number(atendimento.valor_final))}</span>
          </div>
        )}
        <div className="mt-2">
          <span className="font-mono text-xs text-text-muted">{detalhe.cliente.telefone}</span>
        </div>
        <div className="mt-3">
          <AcoesAtendimento
            atendimento={atendimento}
            onDevolver={onDevolver}
            onFechar={onFechar}
            onPerder={onPerder}
          />
        </div>
      </div>

      <ResumoAtendimento detalhe={detalhe} />

      <SecaoColapsavel titulo="Histórico de mensagens" count={detalhe.mensagens.length} defaultOpen={atendimento.ia_pausada}>
        <HistoricoMensagens mensagens={detalhe.mensagens} />
      </SecaoColapsavel>

      <SecaoColapsavel titulo="Mídias recebidas" count={detalhe.mensagens.filter(m => m.tipo !== "texto" || m.media_object_key).length + detalhe.comprovantes_pix.length}>
        <MidiasRecebidas
          detalhe={detalhe}
          onUploadMidia={onUploadMidia}
          onDeletarMidia={onDeletarMidia}
        />
      </SecaoColapsavel>

      <SecaoColapsavel titulo="Histórico do atendimento" count={detalhe.eventos.length}>
        <Eventos eventos={detalhe.eventos} />
      </SecaoColapsavel>
    </section>
  )
}

function SecaoColapsavel({ titulo, count, defaultOpen, children }: { titulo: string; count?: number; defaultOpen?: boolean; children: ReactNode }) {
  const [aberto, setAberto] = useState(defaultOpen ?? false)
  return (
    <div className="overflow-hidden rounded-lg border border-ink-300 bg-ink-100">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-ink-200"
      >
        <span className="flex-1 text-sm font-semibold text-text-primary">{titulo}</span>
        {count !== undefined && count > 0 && (
          <span className="text-xs text-text-muted">({count})</span>
        )}
        <ChevronDown
          size={16}
          strokeWidth={1.5}
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
  onDeletarMidia: (atendimentoId: string, mensagemId: string) => Promise<void>
}) {
  const [midiaAberta, setMidiaAberta] = useState<MidiaItem | null>(null)
  const [midiaParaDeletar, setMidiaParaDeletar] = useState<MidiaItem | null>(null)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [deleteLoading, setDeleteLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const midias = useMemo<MidiaItem[]>(() => {
    const mensagens = detalhe.mensagens
      .filter((mensagem) => mensagem.tipo !== "texto" || mensagem.media_object_key)
      .map((mensagem) => ({
        id: mensagem.id,
        tipo: mensagem.tipo as "imagem" | "audio" | "texto",
        nome: mensagem.media_object_key?.split("/").pop() ?? mensagem.tipo,
        subtitulo: `${mensagem.tipo} · ${formatDataHora(mensagem.created_at)}`,
        url: mensagem.media_url ?? null,
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
    return [...pix, ...mensagens]
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
      <AlertDialog open={!!midiaAberta} onOpenChange={(open) => !open && setMidiaAberta(null)}>
        <AlertDialogContent className="max-w-4xl rounded-none bg-ink-0 p-0">
          <AlertDialogTitle className="sr-only">{midiaAberta?.nome ?? "Mídia"}</AlertDialogTitle>
          {midiaAberta?.url && (
            midiaAberta.tipo === "audio"
              ? <audio controls src={midiaAberta.url} className="w-full p-4" />
              : <Image
                  src={midiaAberta.url}
                  alt={midiaAberta.nome}
                  width={1200}
                  height={800}
                  unoptimized
                  className="max-h-[82vh] w-full object-contain"
                />
          )}
        </AlertDialogContent>
      </AlertDialog>

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
    <section aria-label="Detalhe do atendimento" aria-busy="true" className="space-y-5">
      <Skeleton className="h-24 rounded-lg" />
      <Skeleton className="h-72 rounded-lg" />
      <div className="rounded-lg border border-ink-300 bg-ink-100 p-6">
        <Skeleton className="mb-4 h-6 w-48" />
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="mb-3 h-16 rounded-lg" />
        ))}
      </div>
      <div className="rounded-lg border border-ink-300 bg-ink-100 p-6">
        <Skeleton className="mb-4 h-6 w-40" />
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="mb-3 h-12 rounded-lg" />
        ))}
      </div>
    </section>
  )
}
