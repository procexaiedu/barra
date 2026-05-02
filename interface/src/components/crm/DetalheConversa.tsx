"use client"

import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type { ConversaDetalheResponse } from "@/tipos/crm"
import { AtendimentoAberto } from "@/components/crm/AtendimentoAberto"
import { DadosCliente } from "@/components/crm/DadosCliente"
import { DadosConversa } from "@/components/crm/DadosConversa"
import { HistoricoAtendimentosConversa } from "@/components/crm/HistoricoAtendimentosConversa"

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
      <div className="flex-1 min-h-0 overflow-y-auto scroll-thin space-y-4 pr-1">
        <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pt-0.5">
          <h1 className="text-lg font-semibold text-text-primary">{cliente}</h1>
          {detalhe.conversa.recorrente && <Badge variant="paused">Recorrente</Badge>}
          <span className="ml-auto text-xs text-text-muted">{ultima}</span>
          <p className="w-full text-[13px] text-text-muted">
            Conversa com <span className="font-medium text-text-primary">{detalhe.modelo.nome}</span>
          </p>
        </header>

        <div className="grid grid-cols-2 gap-4">
          <DadosCliente
            cliente={detalhe.cliente}
            historico={detalhe.historico_atendimentos}
          />

          <DadosConversa conversa={detalhe.conversa} />
        </div>

        <AtendimentoAberto atendimento={detalhe.atendimento_aberto} />

        <HistoricoAtendimentosConversa itens={detalhe.historico_atendimentos} />
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
    <section aria-label="Detalhe da conversa" aria-busy="true" className="space-y-5">
      <Skeleton className="h-16 rounded-lg" />
      <Skeleton className="h-44 rounded-lg" />
      <Skeleton className="h-44 rounded-lg" />
      <Skeleton className="h-44 rounded-lg" />
      <Skeleton className="h-24 rounded-lg" />
      <Skeleton className="h-44 rounded-lg" />
    </section>
  )
}
