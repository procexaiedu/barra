"use client"

import { Suspense, useMemo } from "react"
import { Search } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { DetalheAtendimento } from "@/components/atendimentos/DetalheAtendimento"
import { ListaAtendimentos } from "@/components/atendimentos/ListaAtendimentos"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAtendimentos } from "@/hooks/useAtendimentos"
import type {
  EstadoAtendimento,
  EstadoFiltro,
  FiltrosAtendimentos,
  IaFiltro,
  TipoFiltro,
  UrgenciaFiltro,
} from "@/tipos/atendimentos"
import type { ReactNode } from "react"

const ESTADOS_VALIDOS: ReadonlySet<string> = new Set([
  "Novo",
  "Triagem",
  "Qualificado",
  "Aguardando_confirmacao",
  "Confirmado",
  "Em_execucao",
  "Fechado",
  "Perdido",
])

const estados: { value: EstadoFiltro; label: string }[] = [
  { value: "abertos", label: "Abertos" },
  { value: "Novo", label: "Novo" },
  { value: "Triagem", label: "Triagem" },
  { value: "Qualificado", label: "Qualificado" },
  { value: "Aguardando_confirmacao", label: "Aguardando confirmação" },
  { value: "Confirmado", label: "Confirmado" },
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

  const filtrosOverride = useMemo<Partial<FiltrosAtendimentos>>(() => {
    const override: Partial<FiltrosAtendimentos> = {}
    const estadoQuery = searchParams.get("estado")
    if (estadoQuery && ESTADOS_VALIDOS.has(estadoQuery)) {
      override.estado = estadoQuery as EstadoAtendimento
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

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col gap-2">
      <h1 className="flex-none font-serif text-2xl font-medium leading-none text-text-primary">
        Atendimentos
      </h1>
      <div className="flex-none">
        <Toolbar
          busca={atendimentos.filtros.busca}
          estado={atendimentos.filtros.estado}
          tipo={atendimentos.filtros.tipo}
          urgencia={atendimentos.filtros.urgencia}
          iaFiltro={atendimentos.filtros.ia}
          loading={atendimentos.listaStatus === "loading"}
          onBuscaChange={(busca) => atendimentos.setFiltros((current) => ({ ...current, busca }))}
          onEstadoChange={(estado) => atendimentos.setFiltros((current) => ({ ...current, estado }))}
          onTipoChange={(tipo) => atendimentos.setFiltros((current) => ({ ...current, tipo }))}
          onUrgenciaChange={(urgencia) => atendimentos.setFiltros((current) => ({ ...current, urgencia }))}
          onIaChange={(value) => atendimentos.setFiltros((current) => ({ ...current, ia: value }))}
        />
      </div>

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
    </div>
  )
}

function Toolbar({
  busca,
  estado,
  tipo,
  urgencia,
  iaFiltro,
  loading,
  onBuscaChange,
  onEstadoChange,
  onTipoChange,
  onUrgenciaChange,
  onIaChange,
}: {
  busca: string
  estado: EstadoFiltro
  tipo: TipoFiltro
  urgencia: UrgenciaFiltro
  iaFiltro: IaFiltro
  loading: boolean
  onBuscaChange: (value: string) => void
  onEstadoChange: (value: EstadoFiltro) => void
  onTipoChange: (value: TipoFiltro) => void
  onUrgenciaChange: (value: UrgenciaFiltro) => void
  onIaChange: (value: IaFiltro) => void
}) {
  if (loading) {
    return (
      <div aria-busy="true" className="grid grid-cols-[minmax(160px,1fr)_140px_110px_120px_100px] gap-2">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-9 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(160px,1fr)_140px_110px_120px_100px] gap-2">
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
        className="h-9 w-full rounded-lg border border-input bg-ink-100 px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {children}
      </select>
    </label>
  )
}
