"use client"

import { useState } from "react"
import { ChevronDown, SlidersHorizontal } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { SeletorPerfis } from "@/components/clientes/SeletorPerfis"
import {
  FiltroMotivoPerda,
  FiltroValorRange,
  SeletorDesfecho,
  SeletorRecencia,
  type FiltroDesfecho,
  type FiltroRecencia,
} from "@/components/clientes/MapaControles"
import { FILTROS_MAPA_PADRAO } from "@/hooks/useClientesMapa"
import type { MotivoPerda, PerfilFisico } from "@/tipos/clientes"

/** Popover único que agrupa filtros do Mapa que antes viviam soltos na barra
 *  (Perfil físico, Desfecho, Motivo, Faixa de R$, Recência, Incluir arquivados).
 *  Período e Modelo continuam visíveis na MapaToolbar — são os filtros mais usados.
 *  Busca não entra porque o endpoint do mapa ignora `q` (ver useClientesMapa). */
export function PopoverFiltrosMapa({
  perfis,
  onPerfisChange,
  desfecho,
  onDesfechoChange,
  motivosPerda,
  onMotivosPerdaChange,
  valorMin,
  valorMax,
  onValorRangeChange,
  recencia,
  onRecenciaChange,
  incluirArquivados,
  onIncluirArquivadosChange,
  lenteDemandaAtiva,
  compararAtivo,
}: {
  perfis: PerfilFisico[]
  onPerfisChange: (v: PerfilFisico[]) => void
  desfecho: FiltroDesfecho
  onDesfechoChange: (v: FiltroDesfecho) => void
  motivosPerda: MotivoPerda[]
  onMotivosPerdaChange: (v: MotivoPerda[]) => void
  valorMin: number | null
  valorMax: number | null
  onValorRangeChange: (range: { valorMin: number | null; valorMax: number | null }) => void
  recencia: FiltroRecencia
  onRecenciaChange: (v: FiltroRecencia) => void
  incluirArquivados: boolean
  onIncluirArquivadosChange: (v: boolean) => void
  /** Quando a lente "Demanda não atendida" está ON, Desfecho/Motivo ficam disabled
   *  (mesmo padrão de bloqueio dos seletores soltos). */
  lenteDemandaAtiva: boolean
  /** MAPA-14: quando Comparar está ON, a Recência fica disabled (recortes
   *  absolutos substituem a noção de cutoff relativo; o backend ignora o param). */
  compararAtivo?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ativos = contarFiltrosAtivos({
    perfis,
    desfecho,
    motivosPerda,
    valorMin,
    valorMax,
    recencia,
    incluirArquivados,
  })

  const limparTudo = () => {
    onPerfisChange([])
    onDesfechoChange(FILTROS_MAPA_PADRAO.desfecho)
    onMotivosPerdaChange([])
    onValorRangeChange({
      valorMin: FILTROS_MAPA_PADRAO.valorMin,
      valorMax: FILTROS_MAPA_PADRAO.valorMax,
    })
    onRecenciaChange(FILTROS_MAPA_PADRAO.recencia)
    onIncluirArquivadosChange(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label="Mais filtros do mapa"
        className={cn(
          "flex h-9 items-center gap-2 rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        )}
      >
        <SlidersHorizontal size={14} strokeWidth={1.5} className="text-text-muted" />
        <span>Filtros</span>
        {ativos > 0 && (
          <span className="shrink-0 rounded-full bg-gold-500/15 px-1.5 text-[10px] font-semibold text-gold-500 tabular-nums">
            {ativos}
          </span>
        )}
        <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[340px] p-0">
        <div className="flex max-h-[70vh] flex-col">
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <span className="text-sm font-medium text-text-primary">Filtros do mapa</span>
            {ativos > 0 && (
              <button
                type="button"
                onClick={limparTudo}
                className="rounded-md px-2 py-1 text-[12px] font-medium text-text-muted outline-none transition-colors hover:bg-accent hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring"
              >
                Limpar todos
              </button>
            )}
          </div>
          <div className="flex flex-col gap-4 overflow-y-auto px-4 py-3">
            <Secao label="Perfil físico do cliente">
              <SeletorPerfis
                value={perfis}
                onChange={onPerfisChange}
                idPrefix="filtro-mapa-perfil"
              />
            </Secao>
            <Secao label="Último atendimento">
              <SeletorDesfecho
                desfecho={desfecho}
                onDesfechoChange={onDesfechoChange}
                bloqueada={lenteDemandaAtiva}
              />
            </Secao>
            {desfecho === "Perdido" && (
              <Secao label="Por que perdeu">
                <FiltroMotivoPerda
                  desfecho={desfecho}
                  motivosPerda={motivosPerda}
                  onMotivosPerdaChange={onMotivosPerdaChange}
                  bloqueada={lenteDemandaAtiva}
                />
              </Secao>
            )}
            <Secao label="Quanto o cliente já gastou">
              <FiltroValorRange
                valorMin={valorMin}
                valorMax={valorMax}
                onChange={onValorRangeChange}
              />
            </Secao>
            <Secao label="Última visita">
              <SeletorRecencia
                recencia={recencia}
                onRecenciaChange={onRecenciaChange}
                bloqueada={compararAtivo}
              />
            </Secao>
            <label className="flex cursor-pointer select-none items-center gap-2 border-t border-border pt-3 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={incluirArquivados}
                onChange={(e) => onIncluirArquivadosChange(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-input bg-transparent accent-primary"
              />
              Mostrar também clientes arquivados
            </label>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function Secao({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
        {label}
      </span>
      {children}
    </div>
  )
}

function contarFiltrosAtivos(args: {
  perfis: PerfilFisico[]
  desfecho: FiltroDesfecho
  motivosPerda: MotivoPerda[]
  valorMin: number | null
  valorMax: number | null
  recencia: FiltroRecencia
  incluirArquivados: boolean
}): number {
  let n = 0
  if (args.perfis.length > 0) n++
  if (args.desfecho !== FILTROS_MAPA_PADRAO.desfecho) n++
  if (args.motivosPerda.length > 0) n++
  if (args.valorMin !== null || args.valorMax !== null) n++
  if (args.recencia !== FILTROS_MAPA_PADRAO.recencia) n++
  if (args.incluirArquivados) n++
  return n
}
