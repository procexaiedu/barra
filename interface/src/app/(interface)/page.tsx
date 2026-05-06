"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { CheckCircle2, CalendarOff, LayoutList, LayoutGrid, Eye } from "lucide-react"
import Link from "next/link"
import { usePainelResumo } from "@/hooks/usePainelResumo"
import { useTileFlash } from "@/hooks/useTileFlash"
import { useCardEntrada } from "@/hooks/useCardEntrada"
import { useDetalheMetrica } from "@/hooks/useDetalheMetrica"
import { HeaderPainel } from "@/components/painel/HeaderPainel"
import { CardDestaque } from "@/components/painel/CardDestaque"
import { TileMetrica } from "@/components/painel/TileMetrica"
import { LinhaAgenda } from "@/components/painel/LinhaAgenda"
import { ModalDetalheMetrica } from "@/components/painel/ModalDetalheMetrica"
import { ModalDecisaoCard } from "@/components/painel/ModalDecisaoCard"
import { ModalDetalheAgenda } from "@/components/painel/ModalDetalheAgenda"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { formatBRL, formatDiaSemana, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { ItemAberto, ItemFechamento, ItemPerda, CardDestaque as CardDestaqueType, LinhaAgenda as LinhaAgendaType } from "@/tipos/painel"

const TITULO_MODAL = {
  abertos: "Atendimentos em aberto",
  fechamentos: "Fechamentos de hoje",
  perdas: "Perdas de hoje",
} as const

const ROW_CLS = cn(
  "grid w-full items-center gap-3 rounded-md px-1 py-1.5 text-left text-[13px]",
  "transition-colors hover:bg-ink-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
)

function ListaAbertos({
  itens,
  mostrarModelo,
  onNavegar,
}: {
  itens: ItemAberto[]
  mostrarModelo: boolean
  onNavegar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhum atendimento em aberto.</p>
  return (
    <ul className="flex flex-col">
      {itens.map((item) => (
        <li key={item.atendimento_id}>
          <button type="button" onClick={() => onNavegar(item.atendimento_id)}
            className={cn(ROW_CLS, "group grid-cols-[1fr_auto_auto]")}>
            <span className="truncate text-text-primary">
              {item.cliente_nome ?? "—"}
              {mostrarModelo
                ? <span className="ml-1 text-text-muted">({item.modelo_nome} #{item.numero_curto})</span>
                : <span className="ml-1 text-text-muted">#{item.numero_curto}</span>}
            </span>
            <span className="text-xs text-text-muted">{item.estado.replace(/_/g, " ")}</span>
            <Eye size={13} strokeWidth={1.75} aria-hidden className="text-text-muted/30 transition-colors group-hover:text-text-muted" />
          </button>
        </li>
      ))}
    </ul>
  )
}

function ResumoModelosFechamentos({ itens }: { itens: ItemFechamento[] }) {
  const por_modelo = Object.values(
    itens.reduce<Record<string, { nome: string; bruto: number; lucro: number }>>((acc, item) => {
      const key = item.modelo_nome
      if (!acc[key]) acc[key] = { nome: item.modelo_nome, bruto: 0, lucro: 0 }
      acc[key].bruto += item.valor_final ?? 0
      acc[key].lucro += item.lucro ?? 0
      return acc
    }, {})
  ).sort((a, b) => b.bruto - a.bruto)

  return (
    <div className="mb-3 rounded-md bg-ink-200 px-3 py-2">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-text-muted">Por modelo</p>
      <div className="flex flex-col gap-1">
        {por_modelo.map((m) => (
          <div key={m.nome} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 text-[13px]">
            <span className="truncate text-text-primary">{m.nome}</span>
            <span className="font-mono text-xs text-text-muted">{formatBRL(m.bruto)}</span>
            <span className="font-mono text-xs text-success-500">{formatBRL(m.lucro)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ListaFechamentos({
  itens,
  mostrarModelo,
  mostrarLucro,
  onNavegar,
}: {
  itens: ItemFechamento[]
  mostrarModelo: boolean
  mostrarLucro: boolean
  onNavegar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhum fechamento hoje.</p>
  return (
    <div className="flex flex-col">
      {mostrarModelo && <ResumoModelosFechamentos itens={itens} />}
      <ul className="flex flex-col">
        {itens.map((item) => (
          <li key={item.atendimento_id}>
            <button type="button" onClick={() => onNavegar(item.atendimento_id)}
              className={cn(ROW_CLS, "group", mostrarLucro ? "grid-cols-[1fr_auto_auto_auto]" : "grid-cols-[1fr_auto_auto]")}>
              <span className="truncate text-text-primary">
                {item.cliente_nome ?? "—"}
                {mostrarModelo
                  ? <span className="ml-1 text-text-muted">({item.modelo_nome} #{item.numero_curto})</span>
                  : <span className="ml-1 text-text-muted">#{item.numero_curto}</span>}
              </span>
              {mostrarLucro && (
                <span className="font-mono text-xs text-text-muted line-through">
                  {item.valor_final != null ? formatBRL(item.valor_final) : "—"}
                </span>
              )}
              <span className="font-mono text-xs text-text-primary">
                {mostrarLucro
                  ? (item.lucro != null ? formatBRL(item.lucro) : "—")
                  : (item.valor_final != null ? formatBRL(item.valor_final) : "—")}
              </span>
              <Eye size={13} strokeWidth={1.75} aria-hidden className="text-text-muted/30 transition-colors group-hover:text-text-muted" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ListaPerdas({
  itens,
  mostrarModelo,
  onNavegar,
}: {
  itens: ItemPerda[]
  mostrarModelo: boolean
  onNavegar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhuma perda hoje.</p>
  return (
    <ul className="flex flex-col">
      {itens.map((item) => (
        <li key={item.atendimento_id}>
          <button type="button" onClick={() => onNavegar(item.atendimento_id)}
            className={cn(ROW_CLS, "group grid-cols-[1fr_auto_auto]")}>
            <span className="truncate text-text-primary">
              {item.cliente_nome ?? "—"}
              {mostrarModelo
                ? <span className="ml-1 text-text-muted">({item.modelo_nome} #{item.numero_curto})</span>
                : <span className="ml-1 text-text-muted">#{item.numero_curto}</span>}
            </span>
            <span className="text-xs text-text-muted">{item.motivo_perda ?? "—"}</span>
            <Eye size={13} strokeWidth={1.75} aria-hidden className="text-text-muted/30 transition-colors group-hover:text-text-muted" />
          </button>
        </li>
      ))}
    </ul>
  )
}

const CARDS_POR_PAGINA = 4

export default function PainelGeral() {
  const router = useRouter()
  const [modeloId, setModeloId] = useState<string | null>(null)
  const [paginaCards, setPaginaCards] = useState(0)
  const [compacto, setCompacto] = useState(false)
  const [cardContexto, setCardContexto] = useState<CardDestaqueType | null>(null)
  const [agendaModal, setAgendaModal] = useState<LinhaAgendaType | null>(null)
  const { data, status, error, refetch } = usePainelResumo(modeloId)

  function handleModeloChange(id: string | null) {
    setPaginaCards(0)
    setModeloId(id)
  }
  const detalhe = useDetalheMetrica(modeloId)
  const novosCardIds = useCardEntrada(data?.cards_destaque ?? [])

  // Título da aba reflete contagem de pendências (antes dos early returns)
  const countPendentes = data?.cards_destaque.length ?? 0
  useEffect(() => {
    document.title = countPendentes > 0 ? `(${countPendentes}) Painel | Barra Vips` : "Painel | Barra Vips"
    return () => { document.title = "Painel | Barra Vips" }
  }, [countPendentes])

  // Hooks chamados antes de early returns — usa 0 como valor inicial seguro
  const m = data?.metricas_dia
  const flashAbertos = useTileFlash(m?.abertos ?? 0)
  const flashFechamentos = useTileFlash(m?.fechamentos_hoje ?? 0)
  const flashPerdas = useTileFlash(m?.perdas_hoje ?? 0)
  const flashValorBruto = useTileFlash(m?.valor_bruto_hoje_brl ?? 0)
  const flashLucro = useTileFlash(m?.lucro_hoje_brl ?? 0)

  if (status === "loading") return <PainelSkeleton />

  if (status === "error" || !data) {
    return (
      <div className="p-8">
        <BannerErro mensagem={error ?? undefined} onRetry={refetch} />
      </div>
    )
  }

  const mostrarModelo = modeloId === null && data.modelos_ativas.length > 1

  const navegar = (atendimentoId: string) => {
    detalhe.fechar()
    router.push(`/atendimentos?id=${atendimentoId}`)
  }

  const tituloModal = detalhe.tituloCustom
    ?? (detalhe.modalAberto === "fechamentos" && detalhe.mostrarLucro
      ? "Lucro de hoje"
      : TITULO_MODAL[detalhe.modalAberto ?? "abertos"])

  const countModal = !detalhe.loading
    ? detalhe.modalAberto === "abertos" ? detalhe.detalheAbertos.length
    : detalhe.modalAberto === "fechamentos" ? detalhe.detalheFechamentos.length
    : detalhe.modalAberto === "perdas" ? detalhe.detalhePerdas.length
    : undefined
    : undefined

  return (
    <div>
      <HeaderPainel
        modelos={data.modelos_ativas}
        modeloId={modeloId}
        onModeloChange={handleModeloChange}
      />

      <section aria-label="Aguardando você" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-primary">Aguardando você</h2>
          {data.cards_destaque.length > 0 && (
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium text-text-muted">
                {data.cards_destaque.length} aguardando ação
              </span>
              <button
                type="button"
                onClick={() => setCompacto((c) => !c)}
                title={compacto ? "Modo grade" : "Modo compacto"}
                className="rounded p-1 text-text-muted transition-colors hover:bg-ink-200 hover:text-text-primary"
              >
                {compacto ? <LayoutGrid size={16} /> : <LayoutList size={16} />}
              </button>
            </div>
          )}
        </div>

        {data.cards_destaque.length > 0 && !compacto && (
          <div className="mb-3 flex items-center gap-5">
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-sm bg-danger-500" />
              Pix em revisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-sm bg-warn-500" />
              Aguardando decisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="h-2 w-2 rounded-sm bg-info-500" />
              Modelo com o cliente
            </span>
          </div>
        )}

        {data.cards_destaque.length === 0 ? (
          <Card className="rounded-lg bg-card p-6">
            <div className="flex items-start gap-3">
              <CheckCircle2 size={20} className="mt-0.5 text-success-500" />
              <div>
                <p className="text-sm text-text-primary">Nada precisa de você agora.</p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Atendimentos que precisarem da sua decisão aparecem aqui.
                </p>
              </div>
            </div>
          </Card>
        ) : compacto ? (
          <Card className="max-h-44 overflow-y-auto rounded-lg bg-card">
            {data.cards_destaque.map((card) => (
              <CardDestaque
                key={card.atendimento_id}
                card={card}
                compacto
                flashing={novosCardIds.has(card.atendimento_id)}
                onAbrirContexto={() => setCardContexto(card)}
              />
            ))}
          </Card>
        ) : (() => {
          const totalPaginas = Math.ceil(data.cards_destaque.length / CARDS_POR_PAGINA)
          const cardsVisiveis = data.cards_destaque.slice(
            paginaCards * CARDS_POR_PAGINA,
            (paginaCards + 1) * CARDS_POR_PAGINA,
          )
          return (
            <>
              <div className="grid gap-4 xl:grid-cols-2">
                {cardsVisiveis.map((card) => (
                  <CardDestaque
                    key={card.atendimento_id}
                    card={card}
                    flashing={novosCardIds.has(card.atendimento_id)}
                    onAbrirContexto={() => setCardContexto(card)}
                  />
                ))}
              </div>
              {totalPaginas > 1 && (
                <div className="mt-4 flex items-center justify-between">
                  <Button variant="ghost" size="sm" disabled={paginaCards === 0}
                    onClick={() => setPaginaCards((p) => p - 1)}>
                    ← Anterior
                  </Button>
                  <span className="text-xs text-text-muted">
                    {paginaCards + 1} / {totalPaginas}
                  </span>
                  <Button variant="ghost" size="sm" disabled={paginaCards >= totalPaginas - 1}
                    onClick={() => setPaginaCards((p) => p + 1)}>
                    Próximo →
                  </Button>
                </div>
              )}
            </>
          )
        })()}
      </section>

      <section aria-label="Métricas de hoje" className="px-8 py-5">
        <div className="mb-4">
          <h2 className="text-base font-semibold text-text-primary">Hoje</h2>
          <p className="mt-0.5 text-xs capitalize text-text-muted">
            {formatDiaSemana(new Date())} · {formatData(new Date().toISOString())}
          </p>
        </div>
        <div className="grid grid-cols-5 gap-4">
          <TileMetrica
            label="ATENDIMENTOS ABERTOS"
            valor={String(data.metricas_dia.abertos)}
            tooltip="Conversas ainda em andamento"
            isZero={data.metricas_dia.abertos === 0}
            flashing={flashAbertos}
            onClick={() => detalhe.abrir("abertos")}
            metricaSecundaria={{ label: "Em handoff", valor: String(data.cards_destaque.length) }}
          />
          <TileMetrica
            label="FECHAMENTOS HOJE"
            valor={String(data.metricas_dia.fechamentos_hoje)}
            colorClass="text-success-500"
            tooltip="Atendimentos pagos e encerrados hoje"
            isZero={data.metricas_dia.fechamentos_hoje === 0}
            tendencia={data.metricas_dia.tendencia && { delta: data.metricas_dia.tendencia.fechamentos_delta, label: "vs ontem" }}
            flashing={flashFechamentos}
            onClick={() => detalhe.abrir("fechamentos")}
            metricaSecundaria={{ label: "Ticket médio", valor: data.metricas_dia.ticket_medio_brl != null ? formatBRL(data.metricas_dia.ticket_medio_brl) : "—" }}
          />
          <TileMetrica
            label="PERDAS HOJE"
            valor={String(data.metricas_dia.perdas_hoje)}
            colorClass="text-danger-500"
            tooltip="Atendimentos que não se converteram hoje"
            isZero={data.metricas_dia.perdas_hoje === 0}
            tendencia={data.metricas_dia.tendencia && { delta: data.metricas_dia.tendencia.perdas_delta, label: "vs ontem", inverso: true }}
            flashing={flashPerdas}
            onClick={() => detalhe.abrir("perdas")}
            metricaSecundaria={{ label: "Conversão", valor: data.metricas_dia.taxa_conversao_pct != null ? `${data.metricas_dia.taxa_conversao_pct.toFixed(0)}%` : "—" }}
          />
          <TileMetrica
            label="VALOR BRUTO HOJE"
            valor={formatBRL(data.metricas_dia.valor_bruto_hoje_brl)}
            tooltip="Soma dos valores finais dos fechamentos"
            isZero={data.metricas_dia.valor_bruto_hoje_brl === 0}
            tendencia={data.metricas_dia.tendencia && { delta: data.metricas_dia.tendencia.valor_bruto_delta_brl, label: "vs ontem", formatDelta: formatBRL }}
            flashing={flashValorBruto}
            onClick={() => detalhe.abrir("fechamentos", false, "Valor bruto de hoje")}
            metricaSecundaria={{ label: "Fechamentos", valor: String(data.metricas_dia.fechamentos_hoje) }}
          />
          <TileMetrica
            label="LUCRO HOJE"
            valor={formatBRL(data.metricas_dia.lucro_hoje_brl)}
            colorClass="text-success-500"
            tooltip="Valor bruto menos repasses às modelos"
            isZero={data.metricas_dia.lucro_hoje_brl === 0}
            flashing={flashLucro}
            onClick={() => detalhe.abrir("fechamentos", true)}
            metricaSecundaria={{ label: "Margem", valor: data.metricas_dia.valor_bruto_hoje_brl > 0 ? `${Math.round(data.metricas_dia.lucro_hoje_brl / data.metricas_dia.valor_bruto_hoje_brl * 100)}%` : "—" }}
          />
        </div>
      </section>

      <section aria-label="Agenda de hoje" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-primary">Agenda de hoje</h2>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/agenda?action=bloquear" />}>
            Bloquear horário
          </Button>
        </div>
        {data.agenda_dia.length === 0 ? (
          <Card className="rounded-lg bg-card p-6">
            <div className="flex items-start gap-3">
              <CalendarOff size={20} className="mt-0.5 text-text-muted" />
              <p className="text-sm text-text-primary">Nenhum horário reservado hoje.</p>
            </div>
          </Card>
        ) : (
          <Card className="overflow-hidden rounded-lg bg-card">
            {data.agenda_dia.map((linha) => (
              <LinhaAgenda
                key={linha.id}
                linha={linha}
                mostrarModelo={mostrarModelo}
                onAbrirDetalhes={() => setAgendaModal(linha)}
              />
            ))}
          </Card>
        )}
      </section>

      <ModalDecisaoCard
        card={cardContexto}
        onClose={() => setCardContexto(null)}
      />

      <ModalDetalheAgenda
        linha={agendaModal}
        onFechar={() => setAgendaModal(null)}
        onBloqueioAlterado={refetch}
      />

      <ModalDetalheMetrica
        titulo={tituloModal}
        count={countModal}
        open={detalhe.modalAberto !== null}
        onOpenChange={(v) => { if (!v) detalhe.fechar() }}
        loading={detalhe.loading}
        error={detalhe.error}
        onRetry={detalhe.retry}
      >
        {detalhe.modalAberto === "abertos" && (
          <ListaAbertos itens={detalhe.detalheAbertos} mostrarModelo={mostrarModelo} onNavegar={navegar} />
        )}
        {detalhe.modalAberto === "fechamentos" && (
          <ListaFechamentos
            itens={detalhe.detalheFechamentos}
            mostrarModelo={mostrarModelo}
            mostrarLucro={detalhe.mostrarLucro}
            onNavegar={navegar}
          />
        )}
        {detalhe.modalAberto === "perdas" && (
          <ListaPerdas itens={detalhe.detalhePerdas} mostrarModelo={mostrarModelo} onNavegar={navegar} />
        )}
      </ModalDetalheMetrica>
    </div>
  )
}

function PainelSkeleton() {
  return (
    <div aria-busy="true">
      <div className="flex items-center justify-between px-8 pb-4 pt-8">
        <Skeleton className="h-12 w-40" />
        <div className="flex gap-6">
          <Skeleton className="h-10 w-32" />
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-48" />
        <div className="grid gap-4 xl:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[120px] rounded-lg" />
          ))}
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-24" />
        <div className="grid grid-cols-5 gap-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-36" />
        <Skeleton className="h-[168px] rounded-lg" />
      </div>
    </div>
  )
}
