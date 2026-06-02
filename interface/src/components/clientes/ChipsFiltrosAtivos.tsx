"use client"

import { X } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatBRL } from "@/lib/formatters"
import { MOTIVO_PERDA_LABEL } from "@/lib/motivoPerda"
import { PERFIL_FISICO_LABEL } from "@/lib/perfilFisico"
import {
  COR_OPORTUNIDADE,
  type FiltroDesfecho,
  type FiltroRecencia,
} from "@/components/clientes/MapaControles"
import { FILTROS_MAPA_PADRAO } from "@/hooks/useClientesMapa"
import type { MotivoPerda, PerfilFisico } from "@/tipos/clientes"

const ROTULO_DESFECHO: Record<Exclude<FiltroDesfecho, "todos">, string> = {
  Fechado: "Fechou",
  Perdido: "Perdeu",
  andamento: "Em andamento",
}

const ROTULO_RECENCIA: Record<Exclude<FiltroRecencia, "todos">, string> = {
  ativos: "Ativos (últimos 90 dias)",
  dormentes: "Dormentes (mais de 90 dias)",
}

/** Linha de chips removíveis para os filtros do Mapa que não estão no default.
 *  Quando a lente "Demanda não atendida" está ON, ela sobrescreve Desfecho/Motivo
 *  no fetch — então mostramos um único chip representando a lente, e omitimos os
 *  chips de Desfecho/Motivo mesmo se houver estado salvo no pai. */
export function ChipsFiltrosAtivos({
  totalNoMapa,
  totalSemLocalizacao,
  perfis,
  desfecho,
  motivosPerda,
  valorMin,
  valorMax,
  recencia,
  incluirArquivados,
  lenteDemanda,
  onLimparPerfis,
  onLimparDesfecho,
  onLimparMotivos,
  onLimparValor,
  onLimparRecencia,
  onLimparArquivados,
  onLimparDemanda,
  onLimparTudo,
}: {
  totalNoMapa: number
  totalSemLocalizacao: number
  perfis: PerfilFisico[]
  desfecho: FiltroDesfecho
  motivosPerda: MotivoPerda[]
  valorMin: number | null
  valorMax: number | null
  recencia: FiltroRecencia
  incluirArquivados: boolean
  lenteDemanda: boolean
  onLimparPerfis: () => void
  onLimparDesfecho: () => void
  onLimparMotivos: () => void
  onLimparValor: () => void
  onLimparRecencia: () => void
  onLimparArquivados: () => void
  onLimparDemanda: () => void
  onLimparTudo: () => void
}) {
  const temPerfis = perfis.length > 0
  // Quando Demanda ON, Desfecho/Motivo são sobrescritos pelo fetch → escondemos
  // os chips para não enganar o usuário (a lente é a verdade visível no mapa).
  const temDesfecho = !lenteDemanda && desfecho !== FILTROS_MAPA_PADRAO.desfecho
  const temMotivos = !lenteDemanda && motivosPerda.length > 0
  const temValor = valorMin !== null || valorMax !== null
  const temRecencia = recencia !== FILTROS_MAPA_PADRAO.recencia
  const totalChips =
    Number(temPerfis) +
    Number(temDesfecho) +
    Number(temMotivos) +
    Number(temValor) +
    Number(temRecencia) +
    Number(incluirArquivados) +
    Number(lenteDemanda)

  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px] text-text-muted">
      <span>
        <span className="font-mono tabular-nums">{totalNoMapa}</span> cliente
        {totalNoMapa === 1 ? "" : "s"} localizado{totalNoMapa === 1 ? "" : "s"}
      </span>
      {totalSemLocalizacao > 0 && (
        <span
          className="rounded-full border border-border bg-card px-3 py-0.5"
          title="Clientes que existem nos filtros mas ainda não têm endereço cadastrado em nenhum atendimento externo."
        >
          <span className="font-mono tabular-nums">{totalSemLocalizacao}</span> sem endereço
        </span>
      )}

      {totalChips > 0 && (
        <span aria-hidden className="text-text-muted">
          ·
        </span>
      )}

      {lenteDemanda && (
        <Chip
          rotulo="Demanda não atendida"
          onRemove={onLimparDemanda}
          tom="oportunidade"
        />
      )}
      {temPerfis && (
        <Chip
          rotulo={`Perfil: ${perfis.map((p) => PERFIL_FISICO_LABEL[p]).join(", ")}`}
          onRemove={onLimparPerfis}
        />
      )}
      {temDesfecho && (
        <Chip
          rotulo={`Último atendimento: ${ROTULO_DESFECHO[desfecho as Exclude<FiltroDesfecho, "todos">]}`}
          onRemove={onLimparDesfecho}
        />
      )}
      {temMotivos && (
        <Chip
          rotulo={
            motivosPerda.length === 1
              ? `Motivo da perda: ${MOTIVO_PERDA_LABEL[motivosPerda[0]]}`
              : `Motivos da perda (${motivosPerda.length})`
          }
          onRemove={onLimparMotivos}
        />
      )}
      {temValor && (
        <Chip
          rotulo={`Já gastou: ${valorMin === null ? "qualquer" : formatBRL(valorMin)} a ${valorMax === null ? "qualquer" : formatBRL(valorMax)}`}
          onRemove={onLimparValor}
        />
      )}
      {temRecencia && (
        <Chip
          rotulo={ROTULO_RECENCIA[recencia as Exclude<FiltroRecencia, "todos">]}
          onRemove={onLimparRecencia}
        />
      )}
      {incluirArquivados && (
        <Chip rotulo="Inclui arquivados" onRemove={onLimparArquivados} />
      )}

      {totalChips > 0 && (
        <button
          type="button"
          onClick={onLimparTudo}
          className="ml-auto rounded-md px-2 py-1 text-[12px] font-medium text-text-muted outline-none transition-colors hover:bg-accent hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring"
        >
          Limpar todos os filtros
        </button>
      )}
    </div>
  )
}

function Chip({
  rotulo,
  onRemove,
  tom,
}: {
  rotulo: string
  onRemove: () => void
  tom?: "oportunidade"
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px]",
        tom === "oportunidade"
          ? "text-text-primary"
          : "border-border bg-card text-text-secondary",
      )}
      style={
        tom === "oportunidade"
          ? { background: `${COR_OPORTUNIDADE}26`, borderColor: COR_OPORTUNIDADE }
          : undefined
      }
    >
      {tom === "oportunidade" && (
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: COR_OPORTUNIDADE }}
        />
      )}
      <span>{rotulo}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remover filtro: ${rotulo}`}
        className="inline-flex items-center rounded-full text-text-muted outline-none transition-colors hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X size={12} strokeWidth={2} />
      </button>
    </span>
  )
}
