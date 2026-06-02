"use client"

import { Suspense, useCallback, useMemo, useState, type ReactNode } from "react"
import { useSearchParams } from "next/navigation"
import { Plus, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { ApiError, api } from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { DetalheCliente } from "@/components/clientes/DetalheCliente"
import { ListaClientes } from "@/components/clientes/ListaClientes"
import { MapaClientes } from "@/components/clientes/MapaClientes"
import { ModalCriarCliente } from "@/components/clientes/ModalCriarCliente"
import { ModalNovoAtendimento } from "@/components/atendimentos/ModalNovoAtendimento"
import { SeletorPerfis } from "@/components/clientes/SeletorPerfis"
import { PageHeader } from "@/components/layout/PageHeader"
import { BuscaFiltro } from "@/components/filtros/BuscaFiltro"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { PainelFiltros } from "@/components/filtros/PainelFiltros"
import { SelectFiltro } from "@/components/filtros/SelectFiltro"
import { useClientes } from "@/hooks/useClientes"
import { FILTROS_MAPA_PADRAO, useClientesMapa } from "@/hooks/useClientesMapa"
import type { FiltrosMapa } from "@/hooks/useClientesMapa"
import type {
  CompararRecortes,
  FiltroDesfecho,
  FiltroRecencia,
} from "@/components/clientes/MapaControles"
import type {
  ClienteListItem,
  MotivoPerda,
  PerfilFisico,
} from "@/tipos/clientes"
import type {
  AtendimentoCriadoResponse,
  CriarAtendimentoRequest,
  CriarAtendimentoResultado,
} from "@/tipos/atendimentos"
import type { PeriodoSelecionado } from "@/tipos/filtros"

export default function Clientes() {
  return (
    <Suspense>
      <ClientesInner />
    </Suspense>
  )
}

function ClientesInner() {
  // Deep-link `?cliente=<id>` (MAPA-5b): vindo do InfoWindow do Mapa de clientes,
  // pré-seleciona o cliente na aba Lista. Consumido só no primeiro mount.
  const searchParams = useSearchParams()
  const [clienteIdInicial] = useState<string | null>(
    () => searchParams?.get("cliente") ?? null
  )
  const crm = useClientes({ selectedIdInicial: clienteIdInicial })
  const [modalCriarAberto, setModalCriarAberto] = useState(false)
  const [aba, setAba] = useState<"lista" | "mapa">("lista")
  // Cliente para o qual abrir o modal "Novo atendimento" (pré-selecionado).
  const [atendimentoParaCliente, setAtendimentoParaCliente] = useState<ClienteListItem | null>(null)
  // MAPA-12: bairro selecionado no mapa filtra a aba Lista. Filtragem client-side
  // por cliente_ids derivados dos pontos do mapa — o endpoint da Lista não tem
  // filtro `bairro` e o `q` filtra nome/telefone, não bairro.
  const [bairroFiltro, setBairroFiltro] = useState<string | null>(null)
  // MAPA-8: filtros que vivem só no Mapa (desfecho + motivos de perda). Ficam no
  // pai porque o hook precisa deles na querystring e o `MapaClientes` precisa dos
  // setters para renderizar os controles.
  const [mapaFiltros, setMapaFiltros] = useState<FiltrosMapa>(FILTROS_MAPA_PADRAO)
  // MAPA-9: lente "Demanda não atendida". Sobrescreve `mapaFiltros` no fetch (sem
  // mutar) quando ON; desligar restaura os filtros prévios do MAPA-8 intactos.
  const [lenteDemanda, setLenteDemanda] = useState(false)
  const mapa = useClientesMapa(
    crm.filtros,
    mapaFiltros,
    crm.incluirArquivados,
    aba === "mapa",
    lenteDemanda,
  )

  const handleDesfechoChange = useCallback((desfecho: FiltroDesfecho) => {
    // Trocar para um desfecho que não é "Perdido" zera os motivos: querystring
    // limpa + sem estado órfão escondido atrás do dropdown desabilitado.
    // MAPA-11 (valor/recência) preserva via spread — ortogonal ao desfecho.
    setMapaFiltros((current) => ({
      ...current,
      desfecho,
      motivosPerda: desfecho === "Perdido" ? current.motivosPerda : [],
    }))
  }, [])

  const handleMotivosPerdaChange = useCallback((motivosPerda: MotivoPerda[]) => {
    setMapaFiltros((current) => ({ ...current, motivosPerda }))
  }, [])

  // MAPA-11: faixa de R$ + recência. Ortogonais ao MAPA-8 e à lente MAPA-9 — não
  // são zeradas ao trocar de desfecho/lente.
  const handleValorRangeChange = useCallback(
    (range: { valorMin: number | null; valorMax: number | null }) => {
      setMapaFiltros((current) => ({ ...current, ...range }))
    },
    [],
  )

  const handleRecenciaChange = useCallback((recencia: FiltroRecencia) => {
    setMapaFiltros((current) => ({ ...current, recencia }))
  }, [])

  // MAPA-14: estado do modo Comparar é um CompararRecortes (toggle + 2 ranges)
  // refletido nos 5 campos do FiltrosMapa. Setter consolidado evita 5 handlers.
  const handleCompararChange = useCallback((next: CompararRecortes) => {
    setMapaFiltros((current) => ({
      ...current,
      comparar: next.comparar,
      aInicio: next.aInicio,
      aFim: next.aFim,
      bInicio: next.bInicio,
      bFim: next.bFim,
    }))
  }, [])

  const compararRecortes: CompararRecortes = {
    comparar: mapaFiltros.comparar,
    aInicio: mapaFiltros.aInicio,
    aFim: mapaFiltros.aFim,
    bInicio: mapaFiltros.bInicio,
    bFim: mapaFiltros.bFim,
  }

  const clienteIdsDoBairro = useMemo(() => {
    if (!bairroFiltro) return null
    return new Set(
      mapa.pontos.filter((p) => p.bairro === bairroFiltro).map((p) => p.cliente_id)
    )
  }, [bairroFiltro, mapa.pontos])

  const itemsLista = useMemo(() => {
    if (!clienteIdsDoBairro) return crm.items
    return crm.items.filter((item) => clienteIdsDoBairro.has(item.id))
  }, [crm.items, clienteIdsDoBairro])

  const filtrarBairro = useCallback((bairro: string) => {
    setBairroFiltro(bairro)
    setAba("lista")
  }, [])

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
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Clientes"
        description="Histórico, recorrência e observações de cada cliente, em todas as modelos."
        action={{
          label: "Novo cliente",
          onClick: () => setModalCriarAberto(true),
          icon: <Plus size={16} strokeWidth={1.5} />,
        }}
      />

      <div role="tablist" aria-label="Visão de clientes" className="flex gap-1 border-b border-border">
        <TabBtn active={aba === "lista"} onClick={() => setAba("lista")}>
          Lista
        </TabBtn>
        <TabBtn active={aba === "mapa"} onClick={() => setAba("mapa")}>
          Mapa
        </TabBtn>
      </div>

      {aba === "lista" ? (
        <>
          <Toolbar
            busca={crm.filtros.busca}
            periodo={{
              periodo: crm.filtros.periodo,
              de: crm.filtros.dataInicio,
              ate: crm.filtros.dataFim,
            }}
            modeloIds={crm.filtros.modeloIds}
            perfis={crm.filtros.perfis}
            recencia={crm.filtros.recencia}
            valorMin={crm.filtros.valorMin}
            valorMax={crm.filtros.valorMax}
            loading={crm.listaStatus === "loading"}
            incluirArquivados={crm.incluirArquivados}
            onBuscaChange={(busca) => crm.setFiltros((current) => ({ ...current, busca }))}
            onPeriodoChange={(p) =>
              crm.setFiltros((current) => ({
                ...current,
                periodo: p.periodo,
                dataInicio: p.periodo === "custom" ? p.de : null,
                dataFim: p.periodo === "custom" ? p.ate : null,
              }))
            }
            onModeloChange={(modeloIds) => crm.setFiltros((current) => ({ ...current, modeloIds }))}
            onPerfisChange={(perfis) => crm.setFiltros((current) => ({ ...current, perfis }))}
            onRecenciaChange={(recencia) => crm.setFiltros((current) => ({ ...current, recencia }))}
            onValorRangeChange={({ valorMin, valorMax }) =>
              crm.setFiltros((current) => ({ ...current, valorMin, valorMax }))
            }
            onIncluirArquivadosChange={crm.setIncluirArquivados}
          />
          {bairroFiltro && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-text-secondary">
              <span>
                Bairro:{" "}
                <strong className="font-medium text-text-primary">{bairroFiltro}</strong>
              </span>
              <span aria-hidden className="text-text-muted">·</span>
              <span>
                <span className="font-mono tabular-nums">{itemsLista.length}</span> cliente
                {itemsLista.length === 1 ? "" : "s"}{" "}
                visíve{itemsLista.length === 1 ? "l" : "is"}
              </span>
              <button
                type="button"
                onClick={() => setBairroFiltro(null)}
                aria-label="Limpar filtro de bairro"
                className="ml-auto inline-flex items-center gap-1 rounded-md text-text-muted transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X size={14} strokeWidth={1.5} />
                <span>Limpar</span>
              </button>
            </div>
          )}
          <div className="grid h-[calc(100vh-240px)] grid-cols-[360px_minmax(0,1fr)] gap-5 overflow-hidden">
            <ListaClientes
              items={itemsLista}
              selectedId={crm.selectedId}
              status={crm.listaStatus}
              error={crm.listaError}
              filtrosAplicados={crm.filtrosAplicados || bairroFiltro !== null}
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
        </>
      ) : (
        <MapaClientes
          pontos={mapa.pontos}
          totalSemLocalizacao={mapa.totalSemLocalizacao}
          status={mapa.status}
          error={mapa.error}
          onRetry={mapa.refetch}
          onFiltrarBairro={filtrarBairro}
          desfecho={mapaFiltros.desfecho}
          motivosPerda={mapaFiltros.motivosPerda}
          onDesfechoChange={handleDesfechoChange}
          onMotivosPerdaChange={handleMotivosPerdaChange}
          lenteDemanda={lenteDemanda}
          onLenteDemandaChange={setLenteDemanda}
          valorMin={mapaFiltros.valorMin}
          valorMax={mapaFiltros.valorMax}
          recencia={mapaFiltros.recencia}
          onValorRangeChange={handleValorRangeChange}
          onRecenciaChange={handleRecenciaChange}
          periodo={crm.filtros.periodo}
          dataInicio={crm.filtros.dataInicio}
          dataFim={crm.filtros.dataFim}
          modeloIds={crm.filtros.modeloIds}
          perfis={crm.filtros.perfis}
          incluirArquivados={crm.incluirArquivados}
          onPeriodoChange={(periodo) => crm.setFiltros((current) => ({ ...current, periodo }))}
          onCustomPeriodoChange={({ dataInicio, dataFim }) =>
            crm.setFiltros((current) => ({ ...current, dataInicio, dataFim }))
          }
          onModeloChange={(modeloIds) => crm.setFiltros((current) => ({ ...current, modeloIds }))}
          onPerfisChange={(perfis) => crm.setFiltros((current) => ({ ...current, perfis }))}
          onIncluirArquivadosChange={crm.setIncluirArquivados}
          comparar={compararRecortes}
          onCompararChange={handleCompararChange}
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
  modeloIds,
  perfis,
  recencia,
  valorMin,
  valorMax,
  loading,
  incluirArquivados,
  onBuscaChange,
  onPeriodoChange,
  onModeloChange,
  onPerfisChange,
  onRecenciaChange,
  onValorRangeChange,
  onIncluirArquivadosChange,
}: {
  busca: string
  periodo: PeriodoSelecionado
  modeloIds: string[]
  perfis: PerfilFisico[]
  recencia: "ativos" | "dormentes" | null
  valorMin: number | null
  valorMax: number | null
  loading: boolean
  incluirArquivados: boolean
  onBuscaChange: (value: string) => void
  onPeriodoChange: (value: PeriodoSelecionado) => void
  onModeloChange: (value: string[]) => void
  onPerfisChange: (value: PerfilFisico[]) => void
  onRecenciaChange: (value: "ativos" | "dormentes" | null) => void
  onValorRangeChange: (range: { valorMin: number | null; valorMax: number | null }) => void
  onIncluirArquivadosChange: (value: boolean) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(260px,1fr)_140px_180px] gap-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-16 rounded-md" />
            <Skeleton className="h-9 rounded-lg" />
          </div>
        ))}
      </div>
    )
  }
  const faixaValorAtiva = valorMin != null || valorMax != null
  const filtrosSecundariosAtivos =
    perfis.length +
    (incluirArquivados ? 1 : 0) +
    (recencia ? 1 : 0) +
    (faixaValorAtiva ? 1 : 0)
  return (
    <div className="flex flex-wrap items-end gap-3">
      <BuscaFiltro
        value={busca}
        onChange={onBuscaChange}
        placeholder="Buscar nome ou telefone"
        className="min-w-[260px] flex-1"
      />
      <FiltroPeriodo value={periodo} onChange={onPeriodoChange} />
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-text-muted">Modelo</span>
        <FiltroModelo value={modeloIds} onChange={onModeloChange} />
      </div>
      <PainelFiltros
        ativos={filtrosSecundariosAtivos}
        onLimpar={() => {
          onPerfisChange([])
          onRecenciaChange(null)
          onValorRangeChange({ valorMin: null, valorMax: null })
          onIncluirArquivadosChange(false)
        }}
      >
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-text-muted">Perfil físico</span>
          <SeletorPerfis value={perfis} onChange={onPerfisChange} idPrefix="filtro-perfil" />
        </div>
        <SelectFiltro
          label="Recência"
          value={recencia ?? "todos"}
          onChange={(v) => onRecenciaChange(v === "todos" ? null : (v as "ativos" | "dormentes"))}
        >
          <option value="todos">Qualquer atividade</option>
          <option value="ativos">Ativos (até 90 dias)</option>
          <option value="dormentes">Dormentes (90+ dias)</option>
        </SelectFiltro>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-text-muted">Valor fechado (R$)</span>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              inputMode="numeric"
              min={0}
              value={valorMin ?? ""}
              onChange={(e) =>
                onValorRangeChange({
                  valorMin: e.target.value === "" ? null : Number(e.target.value),
                  valorMax,
                })
              }
              placeholder="Mín"
              aria-label="Valor mínimo"
              className="h-9"
            />
            <span className="text-text-muted">–</span>
            <Input
              type="number"
              inputMode="numeric"
              min={0}
              value={valorMax ?? ""}
              onChange={(e) =>
                onValorRangeChange({
                  valorMin,
                  valorMax: e.target.value === "" ? null : Number(e.target.value),
                })
              }
              placeholder="Máx"
              aria-label="Valor máximo"
              className="h-9"
            />
          </div>
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
      </PainelFiltros>
    </div>
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
        "relative px-3 pb-2.5 pt-1 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-gold-500"
          : "text-text-muted hover:text-text-secondary"
      )}
    >
      {children}
    </button>
  )
}
