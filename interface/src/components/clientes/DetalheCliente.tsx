"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { formatData, formatTelefone, formatTempoRelativo } from "@/lib/formatters"
import type {
  Cliente,
  ClienteConversaResumo,
  ClienteDetalheResponse,
  ClienteListItem,
  ConversaDetalheResponse,
  EditarClienteRequest,
} from "@/tipos/clientes"
import { AtendimentoAberto } from "@/components/clientes/AtendimentoAberto"
import { DadosCliente } from "@/components/clientes/DadosCliente"
import { DadosConversa } from "@/components/clientes/DadosConversa"
import { GraficoReceita } from "@/components/clientes/GraficoReceita"
import { HistoricoAtendimentosConversa } from "@/components/clientes/HistoricoAtendimentosConversa"
import { Observacoes } from "@/components/clientes/Observacoes"

export function DetalheCliente({
  detalhe,
  conversas,
  conversaAtivaId,
  clienteSemHistorico,
  status,
  error,
  arquivado,
  onRetry,
  onSelecionarConversa,
  onEditarCliente,
  onArquivarCliente,
  onDesarquivarCliente,
  onCriarAtendimento,
}: {
  detalhe: ConversaDetalheResponse | null
  conversas: ClienteConversaResumo[]
  conversaAtivaId: string | null
  clienteSemHistorico: ClienteDetalheResponse["cliente"] | null
  status: "loading" | "success" | "error"
  error: string | null
  arquivado?: boolean
  onRetry: () => void
  onSelecionarConversa: (conversaId: string) => void
  onEditarCliente?: (id: string, payload: EditarClienteRequest) => Promise<Cliente>
  onArquivarCliente?: (id: string) => Promise<void>
  onDesarquivarCliente?: (id: string) => Promise<void>
  onCriarAtendimento?: (cliente: ClienteListItem) => void
}) {
  if (status === "loading") return <DetalheSkeleton />
  if (status === "error") return <BannerErro mensagem={error ?? undefined} onRetry={onRetry} />

  // Cliente recém-criado, sem nenhuma conversa/atendimento.
  if (clienteSemHistorico) {
    return (
      <SemHistorico
        cliente={clienteSemHistorico}
        arquivado={Boolean(arquivado)}
        onCriarAtendimento={onCriarAtendimento}
      />
    )
  }

  if (!detalhe) return <EmptyDetalhe />

  const nome = detalhe.cliente.nome ?? formatTelefone(detalhe.cliente.telefone)
  const ultima = detalhe.conversa.ultima_mensagem_em
    ? `Última mensagem ${formatTempoRelativo(detalhe.conversa.ultima_mensagem_em)}`
    : "Sem mensagens ainda"

  return (
    <section aria-label="Detalhe do cliente" className="min-w-0 flex flex-col overflow-hidden">
      <div className="flex-1 min-h-0 overflow-y-auto scroll-thin space-y-3 pr-1">
        <header className="rounded-lg border border-border bg-card px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-center gap-2">
              {detalhe.conversa.recorrente && <Badge variant="paused">Recorrente</Badge>}
              <h1 className="truncate text-xl font-semibold">
                <span className="text-text-muted">Cliente:</span>{" "}
                <span className="text-text-primary">{nome}</span>
              </h1>
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
            <span>
              <span className="text-text-muted">Modelo:</span>{" "}
              <span className="text-text-primary">{detalhe.modelo.nome}</span>
            </span>
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

          {conversas.length > 1 && (
            <SeletorConversa
              conversas={conversas}
              conversaAtivaId={conversaAtivaId}
              onSelecionar={onSelecionarConversa}
            />
          )}
        </header>

        <DadosCliente
          cliente={detalhe.cliente}
          historico={detalhe.historico_atendimentos}
          arquivado={Boolean(arquivado)}
          onEditarCliente={onEditarCliente}
          onArquivarCliente={onArquivarCliente}
          onDesarquivarCliente={onDesarquivarCliente}
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

function SeletorConversa({
  conversas,
  conversaAtivaId,
  onSelecionar,
}: {
  conversas: ClienteConversaResumo[]
  conversaAtivaId: string | null
  onSelecionar: (conversaId: string) => void
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
      <span className="mr-1 text-[11px] uppercase tracking-[0.08em] text-text-muted">
        Modelos:
      </span>
      {conversas.map((conversa) => {
        const ativa = conversa.id === conversaAtivaId
        return (
          <button
            key={conversa.id}
            type="button"
            onClick={() => onSelecionar(conversa.id)}
            aria-pressed={ativa}
            className={
              ativa
                ? "rounded-full border border-state-active bg-accent px-3 py-1 text-xs font-medium text-text-primary"
                : "rounded-full border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:bg-accent hover:text-text-primary"
            }
          >
            {conversa.modelo_nome}
          </button>
        )
      })}
    </div>
  )
}

function SemHistorico({
  cliente,
  arquivado,
  onCriarAtendimento,
}: {
  cliente: ClienteDetalheResponse["cliente"]
  arquivado: boolean
  onCriarAtendimento?: (cliente: ClienteListItem) => void
}) {
  const nome = cliente.nome ?? cliente.telefone_mascarado ?? "Cliente"
  return (
    <section
      aria-label="Detalhe do cliente"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6"
    >
      <div className="flex items-center gap-2">
        {arquivado && <Badge variant="paused">Arquivado</Badge>}
        <h1 className="truncate text-xl font-semibold">
          <span className="text-text-muted">Cliente:</span>{" "}
          <span className="text-text-primary">{nome}</span>
        </h1>
      </div>
      {cliente.telefone_mascarado && (
        <p className="font-mono text-[13px] text-text-muted">{cliente.telefone_mascarado}</p>
      )}
      <p className="text-sm text-text-primary">— Sem histórico</p>
      <p className="text-[13px] text-text-muted">
        Este cliente ainda não tem atendimentos. Crie um atendimento na Central para começar.
      </p>
      <div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onCriarAtendimento?.(cliente)}
          disabled={!onCriarAtendimento}
        >
          Criar atendimento
        </Button>
      </div>
    </section>
  )
}

function EmptyDetalhe() {
  return (
    <section aria-label="Detalhe do cliente" className="rounded-lg border border-border bg-card p-6">
      <p className="text-sm text-text-primary">Nenhum cliente selecionado.</p>
      <p className="mt-1 text-[13px] text-text-muted">
        Selecione um cliente na lista para ver o histórico.
      </p>
    </section>
  )
}

function DetalheSkeleton() {
  return (
    <section aria-label="Detalhe do cliente" aria-busy="true" className="space-y-3">
      <Skeleton className="h-20 rounded-lg" />
      <Skeleton className="h-16 rounded-lg" />
      <Skeleton className="h-16 rounded-lg" />
      <Skeleton className="h-32 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
    </section>
  )
}
