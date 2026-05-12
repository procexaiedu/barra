"use client"

import { useState, type ReactNode } from "react"
import { Plus, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { DetalheConversa } from "@/components/clientes/DetalheConversa"
import { ListaConversas } from "@/components/clientes/ListaConversas"
import { ModalCriarCliente } from "@/components/clientes/ModalCriarCliente"
import { motivoPerdaLabel } from "@/components/clientes/utils"
import { useClientes } from "@/hooks/useClientes"
import type {
  FiltroMotivoPerda,
  FiltroOrdem,
  FiltroPeriodo,
  FiltroRecorrencia,
  ModeloResumo,
  MotivoPerda,
} from "@/tipos/clientes"

const recorrencias: { value: FiltroRecorrencia; label: string }[] = [
  { value: "todas", label: "Todas" },
  { value: "novas", label: "Novas" },
  { value: "recorrentes", label: "Recorrentes" },
]

const motivos: { value: FiltroMotivoPerda; label: string }[] = [
  { value: "todos", label: "Todos" },
  ...(["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] as MotivoPerda[]).map(
    (motivo) => ({ value: motivo, label: motivoPerdaLabel[motivo] })
  ),
]

const periodos: { value: FiltroPeriodo; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "90d", label: "90 dias" },
]

export default function Clientes() {
  const crm = useClientes()
  const [modalCriarAberto, setModalCriarAberto] = useState(false)

  const handleSelecionar = (id: string) => {
    if (id === crm.selectedId) return
    crm.selecionarConversa(id)
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-[40px] font-medium leading-[48px] text-text-primary">
            Clientes
          </h1>
          <p className="mt-1 text-[13px] text-text-muted">
            Histórico, recorrência e observações de cada cliente, por modelo.
          </p>
        </div>
        <Button variant="primary" onClick={() => setModalCriarAberto(true)}>
          <Plus size={16} strokeWidth={1.5} />
          Novo cliente
        </Button>
      </header>

      <Toolbar
        busca={crm.filtros.busca}
        recorrencia={crm.filtros.recorrencia}
        motivoPerda={crm.filtros.motivoPerda}
        periodo={crm.filtros.periodo}
        modeloId={crm.filtros.modeloId}
        ordenarPor={crm.filtros.ordenarPor}
        modelos={crm.modelos}
        loading={crm.listaStatus === "loading"}
        incluirArquivados={crm.incluirArquivados}
        onBuscaChange={(busca) => crm.setFiltros((current) => ({ ...current, busca }))}
        onRecorrenciaChange={(recorrencia) =>
          crm.setFiltros((current) => ({ ...current, recorrencia }))
        }
        onMotivoPerdaChange={(motivoPerda) =>
          crm.setFiltros((current) => ({ ...current, motivoPerda }))
        }
        onPeriodoChange={(periodo) => crm.setFiltros((current) => ({ ...current, periodo }))}
        onModeloChange={(modeloId) => crm.setFiltros((current) => ({ ...current, modeloId }))}
        onOrdemChange={(ordenarPor) => crm.setFiltros((current) => ({ ...current, ordenarPor }))}
        onIncluirArquivadosChange={crm.setIncluirArquivados}
      />

      <div className="grid h-[calc(100vh-240px)] grid-cols-[360px_minmax(0,1fr)] gap-5 overflow-hidden">
        <ListaConversas
          items={crm.items}
          selectedId={crm.selectedId}
          status={crm.listaStatus}
          error={crm.listaError}
          filtrosAplicados={crm.filtrosAplicados}
          nextCursor={crm.nextCursor}
          ordenarPor={crm.filtros.ordenarPor}
          onSelect={handleSelecionar}
          onRetry={crm.refetch}
          onCarregarMais={crm.carregarMais}
        />
        <DetalheConversa
          detalhe={crm.detalhe}
          status={crm.detalheStatus}
          error={crm.detalheError}
          arquivado={
            crm.detalhe ? crm.idsArquivados.has(crm.detalhe.cliente.id) : false
          }
          onRetry={crm.refetch}
          onEditarCliente={crm.editarCliente}
          onArquivarCliente={crm.arquivarCliente}
          onDesarquivarCliente={crm.desarquivarCliente}
        />
      </div>

      <ModalCriarCliente
        open={modalCriarAberto}
        onClose={() => setModalCriarAberto(false)}
        onCriar={crm.criarCliente}
      />
    </div>
  )
}

function Toolbar({
  busca,
  recorrencia,
  motivoPerda,
  periodo,
  modeloId,
  ordenarPor,
  modelos,
  loading,
  incluirArquivados,
  onBuscaChange,
  onRecorrenciaChange,
  onMotivoPerdaChange,
  onPeriodoChange,
  onModeloChange,
  onOrdemChange,
  onIncluirArquivadosChange,
}: {
  busca: string
  recorrencia: FiltroRecorrencia
  motivoPerda: FiltroMotivoPerda
  periodo: FiltroPeriodo
  modeloId: string
  ordenarPor: FiltroOrdem
  modelos: ModeloResumo[]
  loading: boolean
  incluirArquivados: boolean
  onBuscaChange: (value: string) => void
  onRecorrenciaChange: (value: FiltroRecorrencia) => void
  onMotivoPerdaChange: (value: FiltroMotivoPerda) => void
  onPeriodoChange: (value: FiltroPeriodo) => void
  onModeloChange: (value: string) => void
  onOrdemChange: (value: FiltroOrdem) => void
  onIncluirArquivadosChange: (value: boolean) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(260px,1fr)_140px_180px_140px_180px_160px] gap-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-14 rounded-lg" />
        ))}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[minmax(260px,1fr)_140px_180px_140px_180px_160px] gap-3">
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
        label="Recorrência"
        value={recorrencia}
        onChange={(value) => onRecorrenciaChange(value as FiltroRecorrencia)}
      >
        {recorrencias.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </SelectFiltro>
      <SelectFiltro
        label="Última perda"
        value={motivoPerda}
        onChange={(value) => onMotivoPerdaChange(value as FiltroMotivoPerda)}
      >
        {motivos.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </SelectFiltro>
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
      <SelectFiltro
        label="Ordenar por"
        value={ordenarPor}
        onChange={(value) => onOrdemChange(value as FiltroOrdem)}
      >
        <option value="recente">Mais recente</option>
        <option value="inatividade">Sem fechar há mais tempo</option>
      </SelectFiltro>
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
        className="h-9 w-full rounded-lg border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {children}
      </select>
    </label>
  )
}
