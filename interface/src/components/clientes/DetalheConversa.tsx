"use client"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { formatData, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { ConversaDetalheResponse } from "@/tipos/clientes"
import { AtendimentoAberto } from "@/components/clientes/AtendimentoAberto"
import { DadosCliente } from "@/components/clientes/DadosCliente"
import { DadosConversa } from "@/components/clientes/DadosConversa"
import { GraficoReceita } from "@/components/clientes/GraficoReceita"
import { HistoricoAtendimentosConversa } from "@/components/clientes/HistoricoAtendimentosConversa"
import { Observacoes } from "@/components/clientes/Observacoes"

export function DetalheConversa({
  detalhe,
  status,
  error,
  onRetry,
}: {
  detalhe: ConversaDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  onRetry: () => void
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const cliente = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const ultima = detalhe.conversa.ultima_mensagem_em
    ? `Última mensagem ${formatTempoRelativo(detalhe.conversa.ultima_mensagem_em)}`
    : "Sem mensagens ainda"

  return (
    <section aria-label="Detalhe da conversa" className="min-w-0 flex flex-col overflow-hidden">
      <div className="flex-1 min-h-0 overflow-y-auto scroll-thin space-y-3 pr-1">
        <header className="rounded-lg border border-border bg-card px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-center gap-2">
              {detalhe.conversa.recorrente && <Badge variant="paused">Recorrente</Badge>}
              <h1 className="truncate text-xl font-semibold text-text-primary">{cliente}</h1>
            </div>
            <span className="shrink-0 text-xs text-text-muted">{ultima}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[13px] text-text-muted">
            {detalhe.cliente.nome && (
              <>
                <span className="font-mono">{formatTelefone(detalhe.cliente.telefone)}</span>
                <span>·</span>
              </>
            )}
            <span>{detalhe.modelo.nome}</span>
            {detalhe.cliente.primeiro_contato_modelo_nome && (
              <>
                <span>·</span>
                <span>
                  1º contato:{" "}
                  <span className="text-text-primary">{detalhe.cliente.primeiro_contato_modelo_nome}</span>
                </span>
              </>
            )}
            <span>·</span>
            <span>Cliente desde {formatData(detalhe.cliente.created_at)}</span>
          </div>
        </header>

        <DadosCliente
          cliente={detalhe.cliente}
          historico={detalhe.historico_atendimentos}
        />

        <DadosConversa conversa={detalhe.conversa} />

        <AtendimentoAberto atendimento={detalhe.atendimento_aberto} />

        <HistoricoAtendimentosConversa itens={detalhe.historico_atendimentos} />

        <GraficoReceita historico={detalhe.historico_atendimentos} />

        <Observacoes texto={detalhe.conversa.observacoes_internas} />
      </div>
    </section>
  )
}

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe da conversa" className="rounded-lg border border-border bg-card p-6">
      <p className="text-sm text-text-primary">Nenhuma conversa selecionada.</p>
      <p className="mt-1 text-[13px] text-text-muted">
        Selecione um item da lista para ver o histórico do cliente com a modelo.
      </p>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe da conversa" aria-busy="true" className="space-y-3">
      <Skeleton className="h-20 rounded-lg" />
      <Skeleton className="h-16 rounded-lg" />
      <Skeleton className="h-16 rounded-lg" />
      <Skeleton className="h-32 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
    </section>
  )
}
