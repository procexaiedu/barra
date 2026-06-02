"use client"

import { useState, useEffect } from "react"
import { toast } from "sonner"
import { CheckCircle2, CalendarOff, LayoutList, LayoutGrid, Eye } from "lucide-react"
import { usePainelResumo } from "@/hooks/usePainelResumo"
import { useTileFlash } from "@/hooks/useTileFlash"
import { useCardEntrada } from "@/hooks/useCardEntrada"
import { useDetalheMetrica } from "@/hooks/useDetalheMetrica"
import { dataDeInput, dataInput, dataInputSaoPaulo, isoAgenda } from "@/hooks/useAgenda"
import { PageHeader } from "@/components/layout/PageHeader"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { CardDestaque } from "@/components/painel/CardDestaque"
import { TileMetrica } from "@/components/painel/TileMetrica"
import { LinhaAgenda } from "@/components/painel/LinhaAgenda"
import { ModalDetalheMetrica } from "@/components/painel/ModalDetalheMetrica"
import { ModalDecisaoCard } from "@/components/painel/ModalDecisaoCard"
import { ModalDetalheAgenda } from "@/components/painel/ModalDetalheAgenda"
import { ModalAtendimentoHistorico } from "@/components/clientes/ModalAtendimentoHistorico"
import { DialogBloqueio } from "@/components/agenda/DialogBloqueio"
import { TarefasHojeWidget } from "@/components/tarefas/TarefasHojeWidget"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { formatBRL, formatDiaSemana, formatData } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { ItemAberto, ItemFechamento, ItemPerda, CardDestaque as CardDestaqueType, LinhaAgenda as LinhaAgendaType } from "@/tipos/painel"
import type { AgendaResponse, AtualizarBloqueioInput, BloqueioAgenda, BloqueioFormState } from "@/tipos/agenda"

const TITULO_MODAL = {
  abertos: "Atendimentos em aberto",
  fechamentos: "Fechamentos de hoje",
  perdas: "Perdas de hoje",
} as const

const ROW_CLS = cn(
  "grid w-full items-center gap-3 rounded-md px-2 py-2 text-left text-[13px]",
  "transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
)

function ListaAbertos({
  itens,
  mostrarModelo,
  onVisualizar,
}: {
  itens: ItemAberto[]
  mostrarModelo: boolean
  onVisualizar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhum atendimento em aberto.</p>
  return (
    <ul className="flex flex-col">
      {itens.map((item) => (
        <li key={item.atendimento_id}>
          <button type="button" onClick={() => onVisualizar(item.atendimento_id)}
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
    <div className="mb-3 rounded-md bg-muted px-3 py-2">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">Por modelo</p>
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
  onVisualizar,
}: {
  itens: ItemFechamento[]
  mostrarModelo: boolean
  mostrarLucro: boolean
  onVisualizar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhum fechamento hoje.</p>
  return (
    <div className="flex flex-col">
      {mostrarModelo && <ResumoModelosFechamentos itens={itens} />}
      <ul className="flex flex-col">
        {itens.map((item) => (
          <li key={item.atendimento_id}>
            <button type="button" onClick={() => onVisualizar(item.atendimento_id)}
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
  onVisualizar,
}: {
  itens: ItemPerda[]
  mostrarModelo: boolean
  onVisualizar: (id: string) => void
}) {
  if (itens.length === 0) return <p className="text-sm text-text-muted">Nenhuma perda hoje.</p>
  return (
    <ul className="flex flex-col">
      {itens.map((item) => (
        <li key={item.atendimento_id}>
          <button type="button" onClick={() => onVisualizar(item.atendimento_id)}
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

function fimIsoOvernight(data: string, inicio: string, fim: string): string {
  if (fim !== "24:00" && fim < inicio) {
    const d = dataDeInput(data)
    d.setDate(d.getDate() + 1)
    return isoAgenda(dataInput(d), fim)
  }
  return isoAgenda(data, fim)
}

export default function PainelGeral() {
  const [modeloIds, setModeloIds] = useState<string[]>([])
  // Fluxos de bloqueio precisam de UMA modelo: só quando exatamente uma está filtrada.
  const modeloIdUnico = modeloIds.length === 1 ? modeloIds[0] : null
  const [paginaCards, setPaginaCards] = useState(0)
  const [compacto, setCompacto] = useState(false)
  const [cardContexto, setCardContexto] = useState<CardDestaqueType | null>(null)
  const [agendaModal, setAgendaModal] = useState<LinhaAgendaType | null>(null)
  const [atendimentoHistoricoId, setAtendimentoHistoricoId] = useState<string | null>(null)
  const [bloquearOpen, setBloquearOpen] = useState(false)
  const [bloqueiosMes, setBloqueiosMes] = useState<BloqueioAgenda[]>([])
  const [bloquearInitial, setBloquearInitial] = useState<BloqueioFormState>(() => ({
    data: dataInputSaoPaulo(),
    inicio: "10:00",
    fim: "11:00",
    observacao: "",
  }))
  const { data, status, error, refetch } = usePainelResumo(modeloIds)

  async function abrirBloquear() {
    const hoje = dataInputSaoPaulo()
    setBloquearInitial({ data: hoje, inicio: "10:00", fim: "11:00", observacao: "" })
    setBloquearOpen(true)
    try {
      const base = dataDeInput(hoje)
      const inicioMes = dataInput(new Date(base.getFullYear(), base.getMonth(), 1))
      const fimMes = dataInput(new Date(base.getFullYear(), base.getMonth() + 1, 0))
      const params = new URLSearchParams({
        inicio: `${inicioMes}T00:00:00-03:00`,
        fim: `${fimMes}T23:59:59-03:00`,
      })
      if (modeloIdUnico) params.append("modelo_id", modeloIdUnico)
      const res = await api<AgendaResponse>(`/v1/agenda/bloqueios?${params.toString()}`)
      setBloqueiosMes(res.bloqueios)
    } catch {
      setBloqueiosMes([])
    }
  }

  const criarBloqueio = async (form: BloqueioFormState) => {
    const mId = form.modelo_id ?? modeloIdUnico
    if (!mId) {
      toast.error("Selecione uma modelo.")
      return
    }
    try {
      await api<BloqueioAgenda>("/v1/agenda/bloqueios", {
        method: "POST",
        body: JSON.stringify({
          modelo_id: mId,
          inicio: isoAgenda(form.data, form.inicio),
          fim: fimIsoOvernight(form.data, form.inicio, form.fim),
          observacao: form.observacao.trim() || null,
          ...(form.atendimento_id ? { atendimento_id: form.atendimento_id } : {}),
        }),
      })
      toast.success("Bloqueio criado")
      setBloquearOpen(false)
      refetch()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const atualizarBloqueio = async (
    id: string,
    form: BloqueioFormState,
    atendimentoId?: string | null,
  ) => {
    try {
      const payload: AtualizarBloqueioInput = {
        inicio: isoAgenda(form.data, form.inicio),
        fim: fimIsoOvernight(form.data, form.inicio, form.fim),
        observacao: form.observacao.trim() || null,
      }
      if (atendimentoId !== undefined) payload.atendimento_id = atendimentoId
      await api<BloqueioAgenda>(`/v1/agenda/bloqueios/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      toast.success("Bloqueio atualizado")
      setBloquearOpen(false)
      refetch()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const cancelarBloqueio = async (id: string, confirmar: boolean) => {
    try {
      await api<{ ok: boolean }>(`/v1/agenda/bloqueios/${id}/cancelar`, {
        method: "POST",
        body: JSON.stringify({ confirmar }),
      })
      toast.success("Bloqueio cancelado")
      setBloquearOpen(false)
      refetch()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  function handleModeloChange(ids: string[]) {
    setPaginaCards(0)
    setModeloIds(ids)
  }
  const detalhe = useDetalheMetrica(modeloIds)
  const novosCardIds = useCardEntrada(data?.cards_destaque ?? [])

  // Título da aba reflete contagem de pendências (antes dos early returns)
  const countPendentes = data?.cards_destaque.length ?? 0
  useEffect(() => {
    document.title = countPendentes > 0 ? `(${countPendentes}) Painel | Elite Baby` : "Painel | Elite Baby"
    return () => { document.title = "Painel | Elite Baby" }
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
    return <BannerErro mensagem={error ?? undefined} onRetry={refetch} />
  }

  const mostrarModelo = modeloIds.length !== 1 && data.modelos_ativas.length > 1

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
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Painel"
        description="Tudo que precisa da sua atenção, num só lugar."
      >
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Modelo</span>
          <FiltroModelo value={modeloIds} onChange={handleModeloChange} />
        </div>
      </PageHeader>

      <section aria-label="Aguardando você" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Aguardando você
          </h2>
          {data.cards_destaque.length > 0 && (
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium tabular-nums text-text-muted">
                {data.cards_destaque.length} aguardando ação
              </span>
              <button
                type="button"
                onClick={() => setCompacto((c) => !c)}
                title={compacto ? "Modo grade" : "Modo compacto"}
                aria-label={compacto ? "Modo grade" : "Modo compacto"}
                className="rounded-md p-1 text-text-muted transition-colors hover:bg-accent hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {compacto ? <LayoutGrid size={16} /> : <LayoutList size={16} />}
              </button>
            </div>
          )}
        </div>

        {data.cards_destaque.length > 0 && !compacto && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="size-2 rounded-full bg-state-lost" aria-hidden />
              Pix em revisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="size-2 rounded-full bg-state-handoff" aria-hidden />
              Aguardando decisão
            </span>
            <span className="flex items-center gap-1.5 text-xs text-text-muted">
              <span className="size-2 rounded-full bg-state-info" aria-hidden />
              Modelo com o cliente
            </span>
          </div>
        )}

        {data.cards_destaque.length === 0 ? (
          <Card>
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-success-500/10 ring-1 ring-success-500/20">
                <CheckCircle2 size={22} strokeWidth={1.75} className="text-success-500" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">Nada precisa de você agora.</p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Atendimentos que precisarem da sua decisão aparecem aqui.
                </p>
              </div>
            </div>
          </Card>
        ) : compacto ? (
          <Card className="max-h-44 overflow-y-auto">
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
                <div className="flex items-center justify-between">
                  <Button variant="ghost" size="sm" disabled={paginaCards === 0}
                    onClick={() => setPaginaCards((p) => p - 1)}>
                    ← Anterior
                  </Button>
                  <span className="text-xs tabular-nums text-text-muted">
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

      <section aria-label="Métricas de hoje" className="flex flex-col gap-3">
        <div>
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Hoje
          </h2>
          <p className="mt-1 pl-[14px] text-xs capitalize text-text-muted">
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

      <section aria-label="Agenda de hoje" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Agenda de hoje
          </h2>
          <Button variant="ghost" size="sm" onClick={abrirBloquear}>
            Bloquear horário
          </Button>
        </div>
        {data.agenda_dia.length === 0 ? (
          <Card>
            <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-muted ring-1 ring-border-subtle">
                <CalendarOff size={22} strokeWidth={1.75} className="text-text-muted" />
              </div>
              <div>
                <p className="text-sm font-medium text-text-primary">Nenhum horário reservado hoje.</p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Reservas e bloqueios de hoje aparecem aqui.
                </p>
              </div>
            </div>
          </Card>
        ) : (
          <Card>
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

      <TarefasHojeWidget />

      <ModalDecisaoCard
        card={cardContexto}
        onClose={() => setCardContexto(null)}
        onAbrirHistorico={setAtendimentoHistoricoId}
      />

      <ModalDetalheAgenda
        linha={agendaModal}
        onFechar={() => setAgendaModal(null)}
        onBloqueioAlterado={refetch}
        onAbrirHistorico={setAtendimentoHistoricoId}
      />

      <ModalAtendimentoHistorico
        atendimentoId={atendimentoHistoricoId}
        onClose={() => setAtendimentoHistoricoId(null)}
      />

      {bloquearOpen && (
        <DialogBloqueio
          bloqueio={null}
          modeloId={modeloIdUnico}
          initial={bloquearInitial}
          bloqueios={bloqueiosMes}
          onClose={() => setBloquearOpen(false)}
          onCriar={criarBloqueio}
          onAtualizar={atualizarBloqueio}
          onCancelar={cancelarBloqueio}
          onVerAtendimento={() => {}}
        />
      )}

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
          <ListaAbertos itens={detalhe.detalheAbertos} mostrarModelo={mostrarModelo} onVisualizar={setAtendimentoHistoricoId} />

        )}
        {detalhe.modalAberto === "fechamentos" && (
          <ListaFechamentos
            itens={detalhe.detalheFechamentos}
            mostrarModelo={mostrarModelo}
            mostrarLucro={detalhe.mostrarLucro}
            onVisualizar={setAtendimentoHistoricoId}
          />
        )}
        {detalhe.modalAberto === "perdas" && (
          <ListaPerdas itens={detalhe.detalhePerdas} mostrarModelo={mostrarModelo} onVisualizar={setAtendimentoHistoricoId} />
        )}
      </ModalDetalheMetrica>
    </div>
  )
}

function PainelSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Skeleton className="h-9 w-40 rounded-md" />
          <Skeleton className="mt-2 h-4 w-64 rounded-md" />
        </div>
        <Skeleton className="h-8 w-32 rounded-md" />
      </div>

      <div className="flex flex-col gap-3">
        <Skeleton className="h-6 w-48 rounded-md" />
        <div className="grid gap-4 xl:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[120px] rounded-lg" />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <Skeleton className="h-6 w-24 rounded-md" />
        <div className="grid grid-cols-5 gap-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-[120px] rounded-lg" />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <Skeleton className="h-6 w-36 rounded-md" />
        <Skeleton className="h-[168px] rounded-lg" />
      </div>
    </div>
  )
}
