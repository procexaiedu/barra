"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { LayoutList, Columns, Search } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { DetalheAtendimento } from "@/components/atendimentos/DetalheAtendimento"
import { ListaAtendimentos } from "@/components/atendimentos/ListaAtendimentos"
import { KanbanBoard } from "@/components/atendimentos/KanbanBoard"
import { ModalVisualizacao } from "@/components/atendimentos/ModalVisualizacao"
import { ModalEdicao } from "@/components/atendimentos/ModalEdicao"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAtendimentos } from "@/hooks/useAtendimentos"
import { api } from "@/lib/api"
import type {
  AtendimentoDetalheResponse,
  AtendimentoListaItem,
  AtendimentosListaResponse,
  EstadoFiltro,
  FiltrosAtendimentos,
  IaFiltro,
  QualificacaoFiltro,
  TipoFiltro,
  UrgenciaFiltro,
} from "@/tipos/atendimentos"
import type { ReactNode } from "react"

type ViewMode = "lista" | "kanban"

const ESTADOS_VALIDOS: ReadonlySet<string> = new Set([
  "Qualificando",
  "Aguardando",
  "Em_execucao",
  "Fechado",
  "Perdido",
])

const estados: { value: EstadoFiltro; label: string }[] = [
  { value: "abertos", label: "Abertos" },
  { value: "Qualificando", label: "Qualificando" },
  { value: "Aguardando", label: "Aguardando" },
  { value: "Em_execucao", label: "Em atendimento" },
  { value: "Fechado", label: "Fechado" },
  { value: "Perdido", label: "Perdido" },
]

const tipos: { value: TipoFiltro; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "interno", label: "No local da modelo" },
  { value: "externo", label: "No local do cliente" },
]

const urgencias: { value: UrgenciaFiltro; label: string }[] = [
  { value: "todas", label: "Todas" },
  { value: "imediato", label: "Agora" },
  { value: "agendado", label: "Marcado" },
  { value: "indefinido", label: "Indefinido" },
  { value: "estimado", label: "Estimado" },
]

const ia: { value: IaFiltro; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "ativa", label: "IA ativa" },
  { value: "pausada", label: "IA pausada" },
]

const qualificacoes: { value: QualificacaoFiltro; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "completa", label: "Completa" },
  { value: "incompleta", label: "Incompleta" },
]

export default function CentralAtendimentos() {
  return (
    <Suspense>
      <CentralAtendimentosInner />
    </Suspense>
  )
}

function CentralAtendimentosInner() {
  const searchParams = useSearchParams()
  const initialId = searchParams.get("id")

  const [view, setView] = useState<ViewMode>("lista")

  useEffect(() => {
    const salvo = localStorage.getItem("atendimentos-view")
    if (salvo === "lista" || salvo === "kanban") setView(salvo)
  }, [])

  const handleViewChange = (v: ViewMode) => {
    setView(v)
    localStorage.setItem("atendimentos-view", v)
  }

  const filtrosOverride = useMemo<Partial<FiltrosAtendimentos>>(() => {
    const override: Partial<FiltrosAtendimentos> = {}
    const estadoQuery = searchParams.get("estado")
    if (estadoQuery && ESTADOS_VALIDOS.has(estadoQuery)) {
      override.estado = estadoQuery as EstadoFiltro
    }
    const iaPausada = searchParams.get("ia_pausada")
    if (iaPausada === "true") override.ia = "pausada"
    else if (iaPausada === "false") override.ia = "ativa"
    return override
  }, [searchParams])

  const filtrosUrl = useMemo(
    () => ({
      motivoPerda: searchParams.get("motivo_perda"),
      motivoEscalada: searchParams.get("motivo_escalada"),
    }),
    [searchParams]
  )

  const atendimentos = useAtendimentos(initialId, filtrosOverride, filtrosUrl)

  // Estado do kanban
  const [modalId, setModalId] = useState<string | null>(null)
  const [modalEdicao, setModalEdicao] = useState<AtendimentoDetalheResponse | null>(null)
  const [mostrarEncerrados, setMostrarEncerrados] = useState(false)
  const [itemsEncerrados, setItemsEncerrados] = useState<AtendimentoListaItem[]>([])

  useEffect(() => {
    if (!mostrarEncerrados || view !== "kanban") {
      setItemsEncerrados([])
      return
    }
    let cancelado = false
    Promise.all([
      api<AtendimentosListaResponse>("/v1/atendimentos?estado=Fechado&limit=50"),
      api<AtendimentosListaResponse>("/v1/atendimentos?estado=Perdido&limit=50"),
    ]).then(([fechados, perdidos]) => {
      if (!cancelado) setItemsEncerrados([...fechados.items, ...perdidos.items])
    }).catch(() => {})
    return () => { cancelado = true }
  }, [mostrarEncerrados, view])

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col gap-2">
      <div className="flex-none flex items-center justify-between">
        <h1 className="font-serif text-2xl font-medium leading-none text-text-primary">
          Atendimentos
        </h1>
        <div className="flex items-center gap-1 rounded-lg border border-ink-300 bg-ink-100 p-0.5">
          <ViewButton active={view === "lista"} onClick={() => handleViewChange("lista")} title="Lista">
            <LayoutList size={15} strokeWidth={1.5} />
          </ViewButton>
          <ViewButton active={view === "kanban"} onClick={() => handleViewChange("kanban")} title="Kanban">
            <Columns size={15} strokeWidth={1.5} />
          </ViewButton>
        </div>
      </div>

      <div className="flex-none">
        <Toolbar
          busca={atendimentos.filtros.busca}
          estado={atendimentos.filtros.estado}
          tipo={atendimentos.filtros.tipo}
          urgencia={atendimentos.filtros.urgencia}
          iaFiltro={atendimentos.filtros.ia}
          qualificacaoFiltro={atendimentos.filtros.qualificacao}
          loading={atendimentos.listaStatus === "loading"}
          onBuscaChange={(busca) => atendimentos.setFiltros((current) => ({ ...current, busca }))}
          onEstadoChange={(estado) => atendimentos.setFiltros((current) => ({ ...current, estado }))}
          onTipoChange={(tipo) => atendimentos.setFiltros((current) => ({ ...current, tipo }))}
          onUrgenciaChange={(urgencia) => atendimentos.setFiltros((current) => ({ ...current, urgencia }))}
          onIaChange={(value) => atendimentos.setFiltros((current) => ({ ...current, ia: value }))}
          onQualificacaoChange={(value) => atendimentos.setFiltros((current) => ({ ...current, qualificacao: value }))}
        />
      </div>

      {view === "lista" ? (
        <div className="flex-1 min-h-0 grid grid-cols-[320px_minmax(0,1fr)] gap-3">
          <div className="min-h-0 overflow-y-auto">
            <ListaAtendimentos
              items={atendimentos.items}
              selectedId={atendimentos.selectedId}
              status={atendimentos.listaStatus}
              error={atendimentos.listaError}
              filtrosAplicados={atendimentos.filtrosAplicados}
              nextCursor={atendimentos.nextCursor}
              onSelect={atendimentos.selectAtendimento}
              onRetry={atendimentos.refetch}
              onCarregarMais={atendimentos.carregarMais}
            />
          </div>
          <div className="min-h-0 overflow-y-auto">
            <DetalheAtendimento
              detalhe={atendimentos.detalhe}
              status={atendimentos.detalheStatus}
              error={atendimentos.detalheError}
              onRetry={atendimentos.refetch}
              onDevolver={atendimentos.devolver}
              onFechar={atendimentos.fechar}
              onPerder={atendimentos.perder}
            />
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <KanbanBoard
            items={atendimentos.items}
            itemsEncerrados={itemsEncerrados}
            mostrarEncerrados={mostrarEncerrados}
            onToggleEncerrados={() => setMostrarEncerrados((v) => !v)}
            onCardClick={setModalId}
            onMoverEstado={atendimentos.moverEstado}
          />
          <ModalVisualizacao
            atendimentoId={modalId}
            onClose={() => setModalId(null)}
            onDevolver={atendimentos.devolver}
            onFechar={atendimentos.fechar}
            onPerder={atendimentos.perder}
            onAbrirEdicao={(detalhe) => { setModalEdicao(detalhe); setModalId(null) }}
          />
          <ModalEdicao
            detalhe={modalEdicao}
            onClose={() => setModalEdicao(null)}
            onSalvar={atendimentos.editarDados}
          />
        </div>
      )}
    </div>
  )
}

function ViewButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`flex items-center justify-center rounded-md p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-700 ${active ? "bg-ink-100 text-text-primary shadow-sm" : "text-text-muted hover:text-text-primary"}`}
    >
      {children}
    </button>
  )
}

function Toolbar({
  busca,
  estado,
  tipo,
  urgencia,
  iaFiltro,
  qualificacaoFiltro,
  loading,
  onBuscaChange,
  onEstadoChange,
  onTipoChange,
  onUrgenciaChange,
  onIaChange,
  onQualificacaoChange,
}: {
  busca: string
  estado: EstadoFiltro
  tipo: TipoFiltro
  urgencia: UrgenciaFiltro
  iaFiltro: IaFiltro
  qualificacaoFiltro: QualificacaoFiltro
  loading: boolean
  onBuscaChange: (value: string) => void
  onEstadoChange: (value: EstadoFiltro) => void
  onTipoChange: (value: TipoFiltro) => void
  onUrgenciaChange: (value: UrgenciaFiltro) => void
  onIaChange: (value: IaFiltro) => void
  onQualificacaoChange: (value: QualificacaoFiltro) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(160px,1fr)_140px_110px_120px_100px_110px] gap-2">
        <Skeleton className="h-9 rounded-lg" />
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-9 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(160px,1fr)_140px_110px_120px_100px_110px] gap-2">
      <label className="relative">
        <span className="sr-only">Busca</span>
        <Search size={16} strokeWidth={1.5} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <Input
          value={busca}
          onChange={(event) => onBuscaChange(event.target.value)}
          placeholder="Buscar cliente, telefone ou #N"
          className="pl-9"
        />
      </label>
      <SelectFiltro label="Estado" value={estado} onChange={(value) => onEstadoChange(value as EstadoFiltro)}>
        {estados.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </SelectFiltro>
      <SelectFiltro label="Tipo" value={tipo} onChange={(value) => onTipoChange(value as TipoFiltro)}>
        {tipos.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </SelectFiltro>
      <SelectFiltro label="Quando" value={urgencia} onChange={(value) => onUrgenciaChange(value as UrgenciaFiltro)}>
        {urgencias.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </SelectFiltro>
      <SelectFiltro label="IA" value={iaFiltro} onChange={(value) => onIaChange(value as IaFiltro)}>
        {ia.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </SelectFiltro>
      <SelectFiltro label="Qualificação" value={qualificacaoFiltro} onChange={(value) => onQualificacaoChange(value as QualificacaoFiltro)}>
        {qualificacoes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </SelectFiltro>
    </div>
  )
}

function SelectFiltro({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <label>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-gold-700 focus-visible:ring-offset-2"
      >
        {children}
      </select>
    </label>
  )
}
