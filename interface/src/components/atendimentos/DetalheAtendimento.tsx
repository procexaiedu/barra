"use client"

import { useMemo, useState } from "react"
import Image from "next/image"
import { ChevronDown, FileText, ImageOff } from "lucide-react"
import type { ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { formatDataHora, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { AtendimentoDetalheResponse, MotivoPerda } from "@/tipos/atendimentos"
import { AcoesAtendimento } from "@/components/atendimentos/AcoesAtendimento"
import { HistoricoMensagens } from "@/components/atendimentos/HistoricoMensagens"
import { LinhaEvento } from "@/components/atendimentos/LinhaEvento"
import { ResumoAtendimento } from "@/components/atendimentos/ResumoAtendimento"
import { badgeForEstado, estadoLabel } from "@/components/atendimentos/utils"

interface MidiaItem {
  id: string
  nome: string
  subtitulo: string
  url: string | null
}

export function DetalheAtendimento({
  detalhe,
  status,
  error,
  onRetry,
  onDevolver,
  onFechar,
  onPerder,
}: {
  detalhe: AtendimentoDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
  onDevolver: (id: string) => Promise<void>
  onFechar: (id: string, valorFinal: number) => Promise<void>
  onPerder: (id: string, motivo: MotivoPerda, observacao: string | null) => Promise<void>
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
      <div className={cn("rounded-lg border border-border bg-card p-4 border-l-3", estadoBorder)}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={badgeForEstado(atendimento.estado)}>{estadoLabel[atendimento.estado]}</Badge>
          <h2 className="text-base font-semibold text-text-primary">{cliente}</h2>
          <span className="text-sm text-text-muted">· {detalhe.modelo.nome}</span>
          <span className="ml-auto text-xs font-medium text-text-muted">
            #{atendimento.numero_curto} · {formatTempoRelativo(atendimento.updated_at)}
          </span>
        </div>
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

      <SecaoColapsavel titulo="Histórico de mensagens">
        <HistoricoMensagens mensagens={detalhe.mensagens} />
      </SecaoColapsavel>

      <SecaoColapsavel titulo="Mídias recebidas">
        <MidiasRecebidas detalhe={detalhe} />
      </SecaoColapsavel>

      <SecaoColapsavel titulo="Histórico do atendimento">
        <Eventos eventos={detalhe.eventos} />
      </SecaoColapsavel>
    </section>
  )
}

function SecaoColapsavel({ titulo, children }: { titulo: string; children: ReactNode }) {
  const [aberto, setAberto] = useState(false)
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-hover"
      >
        <span className="flex-1 text-sm font-semibold text-text-primary">{titulo}</span>
        <ChevronDown
          size={16}
          strokeWidth={1.5}
          className={cn("text-text-muted transition-transform duration-150", aberto && "rotate-180")}
        />
      </button>
      {aberto && (
        <div className="border-t border-border p-4">
          {children}
        </div>
      )}
    </div>
  )
}

function MidiasRecebidas({ detalhe }: { detalhe: AtendimentoDetalheResponse }) {
  const [midiaAberta, setMidiaAberta] = useState<MidiaItem | null>(null)
  const midias = useMemo<MidiaItem[]>(() => {
    const mensagens = detalhe.mensagens
      .filter((mensagem) => mensagem.tipo !== "texto" || mensagem.media_object_key)
      .map((mensagem) => ({
        id: mensagem.id,
        nome: mensagem.media_object_key ?? mensagem.tipo,
        subtitulo: `${mensagem.tipo} · ${formatDataHora(mensagem.created_at)}`,
        url: mensagem.media_url ?? null,
      }))
    const pix = detalhe.comprovantes_pix.map((comprovante) => ({
      id: comprovante.id,
      nome: "comprovante Pix",
      subtitulo: `${comprovante.decisao_pipeline} · ${formatDataHora(comprovante.created_at)}`,
      url: null,
    }))
    return [...pix, ...mensagens]
  }, [detalhe])

  return (
    <>
      {midias.length === 0 ? (
        <div className="flex items-start gap-3">
          <ImageOff size={20} strokeWidth={1.5} className="mt-0.5 text-text-muted" />
          <p className="text-sm text-text-primary">Nenhuma mídia recebida neste atendimento.</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {midias.map((midia) => (
            <button
              key={midia.id}
              type="button"
              onClick={() => midia.url && setMidiaAberta(midia)}
              disabled={!midia.url}
              className="inline-flex max-w-full items-center gap-2 rounded-md bg-ink-300 px-3 py-2 font-mono text-xs text-text-muted outline-none transition-colors enabled:hover:bg-ink-200 enabled:hover:text-text-primary disabled:cursor-default focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <FileText size={14} strokeWidth={1.5} />
              <span className="truncate">{midia.nome}</span>
              <span className="font-sans text-text-disabled">{midia.subtitulo}</span>
            </button>
          ))}
        </div>
      )}
      <AlertDialog open={!!midiaAberta} onOpenChange={(open) => !open && setMidiaAberta(null)}>
        <AlertDialogContent className="max-w-4xl rounded-none bg-ink-0 p-0">
          <AlertDialogTitle className="sr-only">{midiaAberta?.nome ?? "Mídia"}</AlertDialogTitle>
          {midiaAberta?.url && (
            <Image
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
    <section aria-label="Detalhe do atendimento" className="rounded-lg border border-border bg-card p-6">
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
      <div className="rounded-lg border border-border bg-card p-6">
        <Skeleton className="mb-4 h-6 w-48" />
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="mb-3 h-16 rounded-lg" />
        ))}
      </div>
      <div className="rounded-lg border border-border bg-card p-6">
        <Skeleton className="mb-4 h-6 w-40" />
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="mb-3 h-12 rounded-lg" />
        ))}
      </div>
    </section>
  )
}
