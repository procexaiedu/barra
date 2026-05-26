"use client"

import type { ReactNode } from "react"
import { ChipsFiltrosAtivos } from "@/components/clientes/ChipsFiltrosAtivos"
import {
  FiltroCompararPeriodos,
  ToggleLenteDemanda,
  type CompararRecortes,
  type FiltroDesfecho,
  type FiltroRecencia,
} from "@/components/clientes/MapaControles"
import { PopoverFiltrosMapa } from "@/components/clientes/PopoverFiltrosMapa"
import { FILTROS_MAPA_PADRAO } from "@/hooks/useClientesMapa"
import type {
  FiltroPeriodo,
  ModeloResumo,
  MotivoPerda,
  PerfilFisico,
} from "@/tipos/clientes"

const PERIODOS: { value: FiltroPeriodo; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "7d", label: "7 dias" },
  { value: "30d", label: "30 dias" },
  { value: "90d", label: "90 dias" },
]

/** Toolbar específica da aba Mapa (substitui o Toolbar superior compartilhado).
 *  Duas linhas:
 *    - Linha 1: Período + Modelo (mais usados, sempre visíveis) + popover "Filtros"
 *      agrupando o resto + CTA "Demanda não atendida".
 *    - Linha 2: chips removíveis dos filtros aplicados + contadores + "Limpar tudo".
 *  Busca não entra porque o endpoint do mapa ignora `q` (useClientesMapa). */
export function MapaToolbar({
  periodo,
  modeloId,
  modelos,
  perfis,
  desfecho,
  motivosPerda,
  valorMin,
  valorMax,
  recencia,
  incluirArquivados,
  lenteDemanda,
  comparar,
  totalNoMapa,
  totalSemLocalizacao,
  onPeriodoChange,
  onModeloChange,
  onPerfisChange,
  onDesfechoChange,
  onMotivosPerdaChange,
  onValorRangeChange,
  onRecenciaChange,
  onIncluirArquivadosChange,
  onLenteDemandaChange,
  onCompararChange,
}: {
  periodo: FiltroPeriodo
  modeloId: string
  modelos: ModeloResumo[]
  perfis: PerfilFisico[]
  desfecho: FiltroDesfecho
  motivosPerda: MotivoPerda[]
  valorMin: number | null
  valorMax: number | null
  recencia: FiltroRecencia
  incluirArquivados: boolean
  lenteDemanda: boolean
  /** MAPA-14: estado do modo Comparar (toggle + 2 recortes). */
  comparar: CompararRecortes
  totalNoMapa: number
  totalSemLocalizacao: number
  onPeriodoChange: (v: FiltroPeriodo) => void
  onModeloChange: (v: string) => void
  onPerfisChange: (v: PerfilFisico[]) => void
  onDesfechoChange: (v: FiltroDesfecho) => void
  onMotivosPerdaChange: (v: MotivoPerda[]) => void
  onValorRangeChange: (range: { valorMin: number | null; valorMax: number | null }) => void
  onRecenciaChange: (v: FiltroRecencia) => void
  onIncluirArquivadosChange: (v: boolean) => void
  onLenteDemandaChange: (v: boolean) => void
  onCompararChange: (next: CompararRecortes) => void
}) {
  const limparTudo = () => {
    onPeriodoChange("todos")
    onModeloChange("todas")
    onPerfisChange([])
    onDesfechoChange(FILTROS_MAPA_PADRAO.desfecho)
    onMotivosPerdaChange([])
    onValorRangeChange({
      valorMin: FILTROS_MAPA_PADRAO.valorMin,
      valorMax: FILTROS_MAPA_PADRAO.valorMax,
    })
    onRecenciaChange(FILTROS_MAPA_PADRAO.recencia)
    onIncluirArquivadosChange(false)
    onLenteDemandaChange(false)
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <SelectInline label="Período" value={periodo} onChange={(v) => onPeriodoChange(v as FiltroPeriodo)}>
          {PERIODOS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </SelectInline>
        <SelectInline label="Modelo" value={modeloId} onChange={onModeloChange}>
          <option value="todas">Todas</option>
          {modelos.map((m) => (
            <option key={m.id} value={m.id}>
              {m.nome}
            </option>
          ))}
        </SelectInline>
        <PopoverFiltrosMapa
          perfis={perfis}
          onPerfisChange={onPerfisChange}
          desfecho={desfecho}
          onDesfechoChange={onDesfechoChange}
          motivosPerda={motivosPerda}
          onMotivosPerdaChange={onMotivosPerdaChange}
          valorMin={valorMin}
          valorMax={valorMax}
          onValorRangeChange={onValorRangeChange}
          recencia={recencia}
          onRecenciaChange={onRecenciaChange}
          incluirArquivados={incluirArquivados}
          onIncluirArquivadosChange={onIncluirArquivadosChange}
          lenteDemandaAtiva={lenteDemanda}
          compararAtivo={comparar.comparar}
        />
        <div className="ml-auto flex items-center gap-2">
          <FiltroCompararPeriodos valor={comparar} onChange={onCompararChange} />
          <ToggleLenteDemanda ativa={lenteDemanda} onAtivaChange={onLenteDemandaChange} />
        </div>
      </div>
      <ChipsFiltrosAtivos
        totalNoMapa={totalNoMapa}
        totalSemLocalizacao={totalSemLocalizacao}
        perfis={perfis}
        desfecho={desfecho}
        motivosPerda={motivosPerda}
        valorMin={valorMin}
        valorMax={valorMax}
        recencia={recencia}
        incluirArquivados={incluirArquivados}
        lenteDemanda={lenteDemanda}
        onLimparPerfis={() => onPerfisChange([])}
        onLimparDesfecho={() => {
          onDesfechoChange(FILTROS_MAPA_PADRAO.desfecho)
          onMotivosPerdaChange([])
        }}
        onLimparMotivos={() => onMotivosPerdaChange([])}
        onLimparValor={() =>
          onValorRangeChange({
            valorMin: FILTROS_MAPA_PADRAO.valorMin,
            valorMax: FILTROS_MAPA_PADRAO.valorMax,
          })
        }
        onLimparRecencia={() => onRecenciaChange(FILTROS_MAPA_PADRAO.recencia)}
        onLimparArquivados={() => onIncluirArquivadosChange(false)}
        onLimparDemanda={() => onLenteDemandaChange(false)}
        onLimparTudo={limparTudo}
      />
    </div>
  )
}

function SelectInline({
  label,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  children: ReactNode
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 min-w-[8rem] rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {children}
      </select>
    </label>
  )
}
