"use client"

import { ChipsFiltrosAtivos } from "@/components/clientes/ChipsFiltrosAtivos"
import {
  FiltroCompararPeriodos,
  ToggleLenteDemanda,
  type CompararRecortes,
  type FiltroDesfecho,
  type FiltroRecencia,
} from "@/components/clientes/MapaControles"
import { PopoverFiltrosMapa } from "@/components/clientes/PopoverFiltrosMapa"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { FILTROS_MAPA_PADRAO } from "@/hooks/useClientesMapa"
import type { PresetPeriodo } from "@/tipos/filtros"
import type { MotivoPerda, PerfilFisico } from "@/tipos/clientes"

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
  periodo: PresetPeriodo
  /** Task 9: janela do "Período personalizado" (ISO `YYYY-MM-DD`). */
  dataInicio: string | null
  dataFim: string | null
  modeloId: string
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
  onPeriodoChange: (v: PresetPeriodo) => void
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
    onPeriodoChange("tudo")
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
        <FiltroPeriodo
          value={{ periodo, de: dataInicio, ate: dataFim }}
          onChange={(v) => {
            onPeriodoChange(v.periodo)
            // Custom carrega o range; qualquer outro preset descarta as datas.
            onCustomPeriodoChange({
              dataInicio: v.periodo === "custom" ? v.de : null,
              dataFim: v.periodo === "custom" ? v.ate : null,
            })
          }}
        />
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
            Modelo
          </span>
          <FiltroModelo
            multi={false}
            value={modeloId === "todas" ? [] : [modeloId]}
            onChange={(ids) => onModeloChange(ids[0] ?? "todas")}
          />
        </div>
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
