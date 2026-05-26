"use client"

import { useCallback, useState, type ReactNode } from "react"
import { Plus, Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { ApiError, api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { DetalheCliente } from "@/components/clientes/DetalheCliente"
import { ListaClientes } from "@/components/clientes/ListaClientes"
import { MapaClientes } from "@/components/clientes/MapaClientes"
import { ModalCriarCliente } from "@/components/clientes/ModalCriarCliente"
import { ModalNovoAtendimento } from "@/components/atendimentos/ModalNovoAtendimento"
import { SeletorPerfis } from "@/components/clientes/SeletorPerfis"
import { useClientes } from "@/hooks/useClientes"
import { useClientesMapa } from "@/hooks/useClientesMapa"
import type {
  ClienteListItem,
  FiltroPeriodo,
  ModeloResumo,
  PerfilFisico,
} from "@/tipos/clientes"
import type {
  AtendimentoCriadoResponse,
  CriarAtendimentoRequest,
  CriarAtendimentoResultado,
} from "@/tipos/atendimentos"

const periodos: { value: FiltroPeriodo; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "90d", label: "90 dias" },
]

export default function Clientes() {
  const crm = useClientes()
  const [modalCriarAberto, setModalCriarAberto] = useState(false)
  const [aba, setAba] = useState<"lista" | "mapa">("lista")
  // Cliente para o qual abrir o modal "Novo atendimento" (pré-selecionado).
  const [atendimentoParaCliente, setAtendimentoParaCliente] = useState<ClienteListItem | null>(null)
  const mapa = useClientesMapa(crm.filtros, crm.incluirArquivados, aba === "mapa")

  const handleSelecionar = (id: string) => {
    if (id === crm.selectedId) return
    crm.selecionarCliente(id)
  }

  const criarAtendimento = useCallback(
    async (payload: CriarAtendimentoRequest): Promise<CriarAtendimentoResultado> => {
      try {
        const res = await api<AtendimentoCriadoResponse>("/v1/atendimentos", {
          method: "POST",
          body: JSON.stringify(payload),
        })
        return { tipo: "criado", atendimento: res }
      } catch (e) {
        if (
          e instanceof ApiError &&
          e.status === 409 &&
          e.detail === "atendimento_aberto_existente"
        ) {
          const atendimentoId = (e.details?.atendimento_id as string | undefined) ?? null
          if (atendimentoId) return { tipo: "existente", atendimento_id: atendimentoId }
        }
        throw e
      }
    },
    []
  )

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-[40px] font-medium leading-[48px] text-text-primary">
            Clientes
          </h1>
          <p className="mt-1 text-[13px] text-text-muted">
            Histórico, recorrência e observações de cada cliente, em todas as modelos.
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalCriarAberto(true)}>
          <Plus size={16} strokeWidth={1.5} />
          Novo cliente
        </Button>
      </header>

      <div role="tablist" aria-label="Visão de clientes" className="flex gap-1 border-b border-border">
        <TabBtn active={aba === "lista"} onClick={() => setAba("lista")}>
          Lista
        </TabBtn>
        <TabBtn active={aba === "mapa"} onClick={() => setAba("mapa")}>
          Mapa
        </TabBtn>
      </div>

      <Toolbar
        busca={crm.filtros.busca}
        periodo={crm.filtros.periodo}
        modeloId={crm.filtros.modeloId}
        perfis={crm.filtros.perfis}
        modelos={crm.modelos}
        loading={crm.listaStatus === "loading"}
        incluirArquivados={crm.incluirArquivados}
        onBuscaChange={(busca) => crm.setFiltros((current) => ({ ...current, busca }))}
        onPeriodoChange={(periodo) => crm.setFiltros((current) => ({ ...current, periodo }))}
        onModeloChange={(modeloId) => crm.setFiltros((current) => ({ ...current, modeloId }))}
        onPerfisChange={(perfis) => crm.setFiltros((current) => ({ ...current, perfis }))}
        onIncluirArquivadosChange={crm.setIncluirArquivados}
      />

      {aba === "lista" ? (
        <div className="grid h-[calc(100vh-240px)] grid-cols-[360px_minmax(0,1fr)] gap-5 overflow-hidden">
          <ListaClientes
            items={crm.items}
            selectedId={crm.selectedId}
            status={crm.listaStatus}
            error={crm.listaError}
            filtrosAplicados={crm.filtrosAplicados}
            nextCursor={crm.nextCursor}
            onSelect={handleSelecionar}
            onRetry={crm.refetch}
            onCarregarMais={crm.carregarMais}
          />
          <DetalheCliente
            detalhe={crm.detalhe}
            conversas={crm.conversas}
            conversaAtivaId={crm.conversaAtivaId}
            clienteSemHistorico={crm.clienteSemHistorico}
            status={crm.detalheStatus}
            error={crm.detalheError}
            arquivado={crm.clienteArquivado}
            onRetry={crm.refetch}
            onSelecionarConversa={crm.selecionarConversa}
            onEditarCliente={crm.editarCliente}
            onArquivarCliente={crm.arquivarCliente}
            onDesarquivarCliente={crm.desarquivarCliente}
            onCriarAtendimento={setAtendimentoParaCliente}
          />
        </div>
      ) : (
        <MapaClientes
          pontos={mapa.pontos}
          totalSemLocalizacao={mapa.totalSemLocalizacao}
          status={mapa.status}
          error={mapa.error}
          onRetry={mapa.refetch}
        />
      )}

      <ModalCriarCliente
        open={modalCriarAberto}
        onClose={() => setModalCriarAberto(false)}
        onCriar={crm.criarCliente}
      />

      {atendimentoParaCliente && (
        <ModalNovoAtendimento
          open
          clienteInicial={atendimentoParaCliente}
          onClose={() => setAtendimentoParaCliente(null)}
          onCriar={criarAtendimento}
          onCriarCliente={crm.criarCliente}
          onCriado={() => {
            // Recarrega o detalhe: o cliente deixa de ser "sem histórico" e passa
            // a exibir o atendimento recém-criado.
            crm.refetch()
          }}
        />
      )}
    </div>
  )
}

function Toolbar({
  busca,
  periodo,
  modeloId,
  perfis,
  modelos,
  loading,
  incluirArquivados,
  onBuscaChange,
  onPeriodoChange,
  onModeloChange,
  onPerfisChange,
  onIncluirArquivadosChange,
}: {
  busca: string
  periodo: FiltroPeriodo
  modeloId: string
  perfis: PerfilFisico[]
  modelos: ModeloResumo[]
  loading: boolean
  incluirArquivados: boolean
  onBuscaChange: (value: string) => void
  onPeriodoChange: (value: FiltroPeriodo) => void
  onModeloChange: (value: string) => void
  onPerfisChange: (value: PerfilFisico[]) => void
  onIncluirArquivadosChange: (value: boolean) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(260px,1fr)_140px_180px] gap-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-14 rounded-lg" />
        ))}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[minmax(260px,1fr)_140px_180px] gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-text-muted">Buscar</span>
          <label className="relative">
            <span className="sr-only">Buscar nome ou telefone</span>
            <Search
              size={16}
              strokeWidth={1.5}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
            />
            <Input
              value={busca}
              onChange={(event) => onBuscaChange(event.target.value)}
              placeholder="Buscar nome ou telefone"
              className="pl-9"
            />
          </label>
        </div>
        <SelectFiltro
          label="Período"
          value={periodo}
          onChange={(value) => onPeriodoChange(value as FiltroPeriodo)}
        >
          {periodos.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </SelectFiltro>
        <SelectFiltro
          label="Modelo"
          value={modeloId}
          onChange={(value) => onModeloChange(value)}
        >
          <option value="todas">Todas</option>
          {modelos.map((modelo) => (
            <option key={modelo.id} value={modelo.id}>
              {modelo.nome}
            </option>
          ))}
        </SelectFiltro>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-text-muted">Perfil físico:</span>
        <SeletorPerfis value={perfis} onChange={onPerfisChange} idPrefix="filtro-perfil" />
      </div>
      <label className="flex w-fit cursor-pointer select-none items-center gap-2 text-xs text-text-muted">
        <input
          type="checkbox"
          checked={incluirArquivados}
          onChange={(e) => onIncluirArquivadosChange(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-input bg-transparent accent-primary"
        />
        Incluir clientes arquivados
      </label>
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
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {children}
      </select>
    </label>
  )
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "relative px-3 pb-2.5 pt-1 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        active
          ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-gold-500"
          : "text-text-muted hover:text-text-secondary"
      )}
    >
      {children}
    </button>
  )
}
