"use client"

import type { ReactNode } from "react"
import { Calendar as CalendarIcon } from "lucide-react"
import { ChipsFiltrosAtivos } from "@/components/clientes/ChipsFiltrosAtivos"
import {
  FiltroCompararPeriodos,
  ToggleLenteDemanda,
  type CompararRecortes,
  type FiltroDesfecho,
  type FiltroRecencia,
} from "@/components/clientes/MapaControles"
import { PopoverFiltrosMapa } from "@/components/clientes/PopoverFiltrosMapa"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { RangeCalendar } from "@/components/ui/range-calendar"
import { formatarDiaMes } from "@/lib/datas"
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
  { value: "custom", label: "Personalizado" },
]

/** Toolbar específica da aba Mapa (substitui o Toolbar superior compartilhado).
 *  Duas linhas:
 *    - Linha 1: Período + Modelo (mais usados, sempre visíveis) + popover "Filtros"
 *      agrupando o resto + CTA "Demanda não atendida".
 *    - Linha 2: chips removíveis dos filtros aplicados + contadores + "Limpar tudo".
 *  Busca não entra porque o endpoint do mapa ignora `q` (useClientesMapa). */
export function MapaToolbar({
  periodo,
  dataInicio,
  dataFim,
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
  onCustomPeriodoChange,
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
  /** Task 9: janela do "Período personalizado" (ISO `YYYY-MM-DD`). */
  dataInicio: string | null
  dataFim: string | null
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
  /** Task 9: aplica/zera a janela custom (datas ISO ou null para limpar). */
  onCustomPeriodoChange: (range: { dataInicio: string | null; dataFim: string | null }) => void
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
    onCustomPeriodoChange({ dataInicio: null, dataFim: null })
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
        <SelectInline
          label="Período"
          value={periodo}
          onChange={(v) => {
            const proximo = v as FiltroPeriodo
            onPeriodoChange(proximo)
            // Trocar de "custom" para um preset/"Todos" descarta as datas — sem
            // estado órfão escondido atrás do dropdown.
            if (proximo !== "custom") {
              onCustomPeriodoChange({ dataInicio: null, dataFim: null })
            }
          }}
        >
          {PERIODOS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </SelectInline>
        {periodo === "custom" && (
          <PeriodoCustom
            dataInicio={dataInicio}
            dataFim={dataFim}
            onChange={onCustomPeriodoChange}
          />
        )}
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
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 min-w-[8rem] rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {children}
      </select>
    </label>
  )
}

/** Task 9: seletor de janela do "Período personalizado". Reusa o RangeCalendar
 *  (react-day-picker) já usado em FiltroPeriodo/DialogRangeCustom. O backend só
 *  filtra quando os dois lados estão preenchidos; enquanto o usuário escolhe só o
 *  início, o fetch ainda não envia o range (buildMapaPath exige inicio <= fim). */
function PeriodoCustom({
  dataInicio,
  dataFim,
  onChange,
}: {
  dataInicio: string | null
  dataFim: string | null
  onChange: (range: { dataInicio: string | null; dataFim: string | null }) => void
}) {
  const rotulo =
    dataInicio && dataFim
      ? `${formatarDiaMes(dataInicio)} – ${formatarDiaMes(dataFim)}`
      : dataInicio
        ? `Desde ${formatarDiaMes(dataInicio)}`
        : "Escolher datas"

  return (
    <Popover>
      <PopoverTrigger
        data-slot="mapa-periodo-custom-trigger"
        className="inline-flex h-9 items-center justify-between gap-1.5 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className="truncate">{rotulo}</span>
        <CalendarIcon size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
      </PopoverTrigger>
      <PopoverContent
        data-slot="mapa-periodo-custom-content"
        align="start"
        className="flex w-[320px] flex-col gap-2 sm:w-[360px]"
      >
        <div className="flex justify-center">
          <RangeCalendar
            value={{ de: dataInicio, ate: dataFim }}
            onChange={(range) => onChange({ dataInicio: range.de, dataFim: range.ate })}
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}
