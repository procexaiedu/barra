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
import { ObservacoesInternas } from "@/components/crm/ObservacoesInternas"

export function DetalheConversa({
  detalhe,
  status,
  error,
  nomeInput,
  observacoesInput,
  observacoesDirty,
  nomeDirty,
  onRetry,
  onAlterarNome,
  onSalvarNome,
  onAlterarObservacoes,
  onSalvarObservacoes,
  onDescartarObservacoes,
}: {
  detalhe: ConversaDetalheResponse | null
  status: "loading" | "success" | "error"
  error: string | null
  nomeInput: string
  observacoesInput: string
  observacoesDirty: boolean
  nomeDirty: boolean
  onRetry: () => void
  onAlterarNome: (valor: string) => void
  onSalvarNome: () => Promise<void>
  onAlterarObservacoes: (valor: string) => void
  onSalvarObservacoes: () => Promise<void>
  onDescartarObservacoes: () => void
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />
  if (!detalhe) return <EmptyDetalhe />

  const cliente = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const ultima = detalhe.conversa.ultima_mensagem_em
    ? `Última mensagem ${formatTempoRelativo(detalhe.conversa.ultima_mensagem_em)}`
    : "Sem mensagens ainda"

  return (
    <section aria-label="Detalhe da conversa" className="min-w-0 space-y-5">
      <header className="rounded-lg border border-border bg-card p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-text-primary">{cliente}</h1>
          {detalhe.conversa.recorrente && <Badge variant="paused">Recorrente</Badge>}
        </div>
        <p className="mt-1 text-[13px] text-text-muted">
          Conversa com <span className="text-text-primary">{detalhe.modelo.nome}</span>
        </p>
        <p className="mt-2 text-xs font-medium text-text-muted">{ultima}</p>
      </header>

      <DadosCliente
        cliente={detalhe.cliente}
        valor={nomeInput}
        dirty={nomeDirty}
        onChange={onAlterarNome}
        onSave={onSalvarNome}
      />

      <DadosConversa conversa={detalhe.conversa} />

      <ObservacoesInternas
        valor={observacoesInput}
        dirty={observacoesDirty}
        onChange={onAlterarObservacoes}
        onSave={onSalvarObservacoes}
        onDescartar={onDescartarObservacoes}
      />

      <AtendimentoAberto atendimento={detalhe.atendimento_aberto} />

      <HistoricoAtendimentosConversa itens={detalhe.historico_atendimentos} />
    </section>
  )
}

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe da conversa" className="rounded-lg border border-border bg-card p-6">
      <p className="text-sm text-text-primary">Nenhuma conversa selecionada.</p>
      <p className="mt-1 text-[13px] text-text-muted">
        Selecione um item da lista para ver o histórico do par cliente e modelo.
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
