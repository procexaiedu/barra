"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import { LayoutList, Columns, Search, Plus } from "lucide-react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { DetalheAtendimento } from "@/components/atendimentos/DetalheAtendimento"
import { FiltroPeriodo } from "@/components/atendimentos/FiltroPeriodo"
import { ListaAtendimentos } from "@/components/atendimentos/ListaAtendimentos"
import { KanbanBoard } from "@/components/atendimentos/KanbanBoard"
import { ModalNovoAtendimento } from "@/components/atendimentos/ModalNovoAtendimento"
import { ModalReatribuir } from "@/components/atendimentos/ModalReatribuir"
import { ModalVisualizacao } from "@/components/atendimentos/ModalVisualizacao"
import { ModalEdicao } from "@/components/atendimentos/ModalEdicao"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAtendimentos } from "@/hooks/useAtendimentos"
import { api } from "@/lib/api"
import { hojeBrtIso } from "@/lib/datas"
import type {
  AtendimentoDetalheResponse,
  AtendimentoListaItem,
  AtendimentosListaResponse,
  EstadoFiltro,
  FiltrosAtendimentos,
  IaFiltro,
  PeriodoFiltro,
  QualificacaoFiltro,
  TipoFiltro,
  UrgenciaFiltro,
} from "@/tipos/atendimentos"
import type { Cliente, CriarClienteRequest } from "@/tipos/clientes"
import type { ReactNode } from "react"

const DATA_ISO_RE = /^\d{4}-\d{2}-\d{2}$/

type ViewMode = "lista" | "kanban"

const VIEW_STORAGE_KEY = "atendimentos-view"

function subscribeViewStorage(callback: () => void): () => void {
  window.addEventListener("storage", callback)
  return () => window.removeEventListener("storage", callback)
}

function getViewSnapshot(): ViewMode {
  const salvo = window.localStorage.getItem(VIEW_STORAGE_KEY)
  return salvo === "lista" || salvo === "kanban" ? salvo : "lista"
}

function getViewServerSnapshot(): ViewMode {
  return "lista"
}

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
  const router = useRouter()
  const pathname = usePathname()
  const initialId = searchParams.get("id")

  const view = useSyncExternalStore<ViewMode>(
    subscribeViewStorage,
    getViewSnapshot,
    getViewServerSnapshot,
  )

  const handleViewChange = (v: ViewMode) => {
    localStorage.setItem(VIEW_STORAGE_KEY, v)
    window.dispatchEvent(new StorageEvent("storage", { key: VIEW_STORAGE_KEY, newValue: v }))
  }

  const criarCliente = useCallback(
    async (payload: CriarClienteRequest): Promise<Cliente> =>
      api<Cliente>("/v1/crm/clientes", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    []
  )

  const filtrosOverride = useMemo<Partial<FiltrosAtendimentos>>(() => {
    const override: Partial<FiltrosAtendimentos> = {}
    const estadoQuery = searchParams.get("estado")
    if (estadoQuery && ESTADOS_VALIDOS.has(estadoQuery)) {
      override.estado = estadoQuery as EstadoFiltro
    }
    const iaPausada = searchParams.get("ia_pausada")
    if (iaPausada === "true") override.ia = "pausada"
    else if (iaPausada === "false") override.ia = "ativa"
    const de = searchParams.get("de")
    const ate = searchParams.get("ate")
    if ((de && DATA_ISO_RE.test(de)) || (ate && DATA_ISO_RE.test(ate))) {
      override.periodo = {
        de: de && DATA_ISO_RE.test(de) ? de : null,
        ate: ate && DATA_ISO_RE.test(ate) ? ate : null,
      }
    }
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

  const aplicarPeriodo = useCallback((proximo: PeriodoFiltro) => {
    atendimentos.setFiltros((current) => ({ ...current, periodo: proximo }))
    const params = new URLSearchParams(searchParams.toString())
    const hoje = hojeBrtIso()
    const ehDefault = proximo.de === hoje && proximo.ate === hoje
    if (ehDefault) {
      params.delete("de")
      params.delete("ate")
    } else {
      if (proximo.de) params.set("de", proximo.de)
      else params.delete("de")
      if (proximo.ate) params.set("ate", proximo.ate)
      else params.delete("ate")
    }
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }, [atendimentos, pathname, router, searchParams])

  // Estado do kanban
  const [modalId, setModalId] = useState<string | null>(null)
  const lastOpenedInitialId = useRef<string | null>(null)

  useEffect(() => {
    if (initialId && view === "kanban" && lastOpenedInitialId.current !== initialId) {
      lastOpenedInitialId.current = initialId
      setModalId(initialId)
    }
  }, [initialId, view])
  const [modalEdicao, setModalEdicao] = useState<AtendimentoDetalheResponse | null>(null)
  const [modalReatribuir, setModalReatribuir] = useState<AtendimentoDetalheResponse | null>(null)
  const [modalNovoAberto, setModalNovoAberto] = useState(false)
  const [mostrarEncerrados, setMostrarEncerrados] = useState(false)
  const [itemsEncerrados, setItemsEncerrados] = useState<AtendimentoListaItem[]>([])

  useEffect(() => {
    if (!mostrarEncerrados || view !== "kanban") {
      return
    }
    let cancelado = false
    Promise.all([
      api<AtendimentosListaResponse>("/v1/atendimentos?estado=Fechado&limit=50"),
      api<AtendimentosListaResponse>("/v1/atendimentos?estado=Perdido&limit=50"),
    ]).then(([fechados, perdidos]) => {
      if (!cancelado) {
        setItemsEncerrados([
          ...(Array.isArray(fechados.items) ? fechados.items : []),
          ...(Array.isArray(perdidos.items) ? perdidos.items : []),
        ])
      }
    }).catch(() => {})
    return () => { cancelado = true }
  }, [mostrarEncerrados, view])

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col gap-2">
      <div className="flex-none flex items-center justify-between">
        <h1 className="font-serif text-2xl font-medium leading-none text-text-primary">
          Atendimentos
        </h1>
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" onClick={() => setModalNovoAberto(true)}>
            <Plus size={14} strokeWidth={1.5} />
            Novo atendimento
          </Button>
          <div className="flex items-center gap-1 rounded-lg border border-ink-300 bg-ink-100 p-0.5">
            <ViewButton active={view === "lista"} onClick={() => handleViewChange("lista")} title="Lista">
              <LayoutList size={15} strokeWidth={1.5} />
            </ViewButton>
            <ViewButton active={view === "kanban"} onClick={() => handleViewChange("kanban")} title="Kanban">
              <Columns size={15} strokeWidth={1.5} />
            </ViewButton>
          </div>
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
          periodo={atendimentos.filtros.periodo}
          loading={atendimentos.listaStatus === "loading"}
          onBuscaChange={(busca) => atendimentos.setFiltros((current) => ({ ...current, busca }))}
          onEstadoChange={(estado) => atendimentos.setFiltros((current) => ({ ...current, estado }))}
          onTipoChange={(tipo) => atendimentos.setFiltros((current) => ({ ...current, tipo }))}
          onUrgenciaChange={(urgencia) => atendimentos.setFiltros((current) => ({ ...current, urgencia }))}
          onIaChange={(value) => atendimentos.setFiltros((current) => ({ ...current, ia: value }))}
          onQualificacaoChange={(value) => atendimentos.setFiltros((current) => ({ ...current, qualificacao: value }))}
          onPeriodoChange={aplicarPeriodo}
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
              onUploadMidia={atendimentos.uploadMidia}
              onDeletarMidia={atendimentos.deletarMidia}
              onEditar={() => setModalEdicao(atendimentos.detalhe)}
            />
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <KanbanBoard
            items={atendimentos.items}
            itemsEncerrados={mostrarEncerrados && view === "kanban" ? itemsEncerrados : []}
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
        </div>
      )}
      <ModalEdicao
        key={modalEdicao?.atendimento?.id ?? ""}
        detalhe={modalEdicao}
        onClose={() => setModalEdicao(null)}
        onSalvar={atendimentos.editarDados}
        onReatribuir={(detalhe) => {
          setModalEdicao(null)
          setModalReatribuir(detalhe)
        }}
      />
      <ModalReatribuir
        detalhe={modalReatribuir}
        onClose={() => setModalReatribuir(null)}
        onCriarCliente={criarCliente}
        onConcluido={async (novoId) => {
          setModalReatribuir(null)
          try {
            const detalhe = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${novoId}`)
            setModalEdicao(detalhe)
          } catch {
            // Falhou: usuário pode abrir manualmente via lista.
          }
          atendimentos.refetch()
        }}
      />
      {modalNovoAberto && (
        <ModalNovoAtendimento
          open
          onClose={() => setModalNovoAberto(false)}
          onCriar={atendimentos.criarAtendimento}
          onCriarCliente={criarCliente}
          onCriado={async (id) => {
            try {
              const detalhe = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`)
              setModalEdicao(detalhe)
            } catch {
              // Falhou: usuário pode abrir manualmente via lista.
            }
          }}
        />
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
  periodo,
  loading,
  onBuscaChange,
  onEstadoChange,
  onTipoChange,
  onUrgenciaChange,
  onIaChange,
  onQualificacaoChange,
  onPeriodoChange,
}: {
  busca: string
  estado: EstadoFiltro
  tipo: TipoFiltro
  urgencia: UrgenciaFiltro
  iaFiltro: IaFiltro
  qualificacaoFiltro: QualificacaoFiltro
  periodo: PeriodoFiltro
  loading: boolean
  onBuscaChange: (value: string) => void
  onEstadoChange: (value: EstadoFiltro) => void
  onTipoChange: (value: TipoFiltro) => void
  onUrgenciaChange: (value: UrgenciaFiltro) => void
  onIaChange: (value: IaFiltro) => void
  onQualificacaoChange: (value: QualificacaoFiltro) => void
  onPeriodoChange: (value: PeriodoFiltro) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(140px,1fr)_140px_110px_120px_100px_110px_150px] gap-2">
        <Skeleton className="h-[54px] rounded-lg" />
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-[54px] rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(140px,1fr)_140px_110px_120px_100px_110px_150px] gap-2">
      <label className="relative flex flex-col gap-0.5">
        <span className="text-xs font-medium text-text-muted">Buscar</span>
        <Search size={16} strokeWidth={1.5} className="pointer-events-none absolute left-3 bottom-2.5 text-text-muted" />
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
      <FiltroPeriodo value={periodo} onChange={onPeriodoChange} />
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
    <label className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-text-muted">{label}</span>
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
