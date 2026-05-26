"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type {
  FiltrosClientes,
  MapaClientesResponse,
  MotivoPerda,
} from "@/tipos/clientes"

/** Filtros que vivem só no Mapa (MAPA-8/MAPA-11). Separados de `FiltrosClientes`
 *  (que é compartilhado com a Lista) para deixar claro o escopo Mapa-only.
 *  MAPA-11 fica aqui ortogonal ao MAPA-8 e à lente MAPA-9 (sempre aplicados no fetch). */
export interface FiltrosMapa {
  desfecho: "todos" | "Fechado" | "Perdido" | "andamento"
  motivosPerda: MotivoPerda[]
  /** MAPA-11: faixa de R$ fechado por cliente (`ag.valor_total`, cross-modelo).
   *  Em reais; `null` = sem limite. */
  valorMin: number | null
  valorMax: number | null
  /** MAPA-11: recência sobre `geo.ultima_data` (externo que ancora o ponto).
   *  Cutoff fixo `RECENCIA_CUTOFF_DIAS` (90 dias). */
  recencia: "todos" | "ativos" | "dormentes"
}

export const FILTROS_MAPA_PADRAO: FiltrosMapa = {
  desfecho: "todos",
  motivosPerda: [],
  valorMin: null,
  valorMax: null,
  recencia: "todos",
}

/** Motivos de perda que a lente "Demanda não atendida" (MAPA-9) considera
 *  oportunidade endereçável — preço/sumiu/risco/outro NÃO entram porque não são
 *  acionáveis por marketing/expansão (são preço, comportamento ou risco). */
export const MOTIVOS_DEMANDA_NAO_ATENDIDA: MotivoPerda[] = [
  "indisponibilidade",
  "fora_de_area",
]

// O mapa respeita os filtros discretos da toolbar (modelo, período, perfil, arquivados).
// `busca` fica de fora de propósito — é busca textual da lista, não do mapa.
function buildMapaPath(
  filtros: FiltrosClientes,
  mapa: FiltrosMapa,
  incluirArquivados: boolean,
  lenteDemandaNaoAtendida: boolean,
) {
  const params = new URLSearchParams()
  if (filtros.periodo !== "todos") params.set("periodo", filtros.periodo)
  if (filtros.modeloId !== "todas") params.set("modelo_id", filtros.modeloId)
  for (const perfil of filtros.perfis) params.append("perfis", perfil)
  if (incluirArquivados) params.set("incluir_arquivados", "true")
  // MAPA-9: a lente SOBRESCREVE desfecho/motivo do MAPA-8 no fetch (não soma).
  // O estado do MAPA-8 fica preservado no pai e volta intacto ao desligar — aqui
  // apenas ignoramos `mapa.desfecho`/`mapa.motivosPerda` enquanto a lente está ON.
  if (lenteDemandaNaoAtendida) {
    params.set("desfecho", "Perdido")
    for (const m of MOTIVOS_DEMANDA_NAO_ATENDIDA) params.append("motivo_perda", m)
  } else {
    if (mapa.desfecho !== "todos") params.set("desfecho", mapa.desfecho)
    // Motivos só fazem sentido quando o desfecho é Perdido — fora disso a UI
    // desabilita o dropdown, mas a defesa em profundidade é não enviar.
    if (mapa.desfecho === "Perdido") {
      for (const m of mapa.motivosPerda) params.append("motivo_perda", m)
    }
  }
  // MAPA-11: faixa de R$ e recência. Omite quando null/"todos" para não poluir a URL.
  // Negativos não chegam aqui (a UI bloqueia no input min={0}); o backend também trata
  // como NO-OP — defesa em profundidade.
  if (mapa.valorMin !== null && mapa.valorMin >= 0) {
    params.set("valor_min", String(mapa.valorMin))
  }
  if (mapa.valorMax !== null && mapa.valorMax >= 0) {
    params.set("valor_max", String(mapa.valorMax))
  }
  if (mapa.recencia !== "todos") params.set("recencia", mapa.recencia)
  const qs = params.toString()
  return `/v1/crm/clientes/mapa${qs ? `?${qs}` : ""}`
}

type Status = "idle" | "loading" | "success" | "error"

/**
 * Carrega os pontos do Mapa de clientes. Só busca quando `enabled` (aba Mapa ativa) e
 * refaz quando os filtros mudam. Mantém os pontos atuais visíveis durante o refetch.
 *
 * MAPA-9: `lenteDemandaNaoAtendida` sobrescreve `mapa.desfecho`/`mapa.motivosPerda`
 * na querystring quando ON (sem mutar o estado do MAPA-8 no pai).
 */
export function useClientesMapa(
  filtros: FiltrosClientes,
  mapa: FiltrosMapa,
  incluirArquivados: boolean,
  enabled: boolean,
  lenteDemandaNaoAtendida: boolean,
) {
  const [data, setData] = useState<MapaClientesResponse | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)

  const path = buildMapaPath(filtros, mapa, incluirArquivados, lenteDemandaNaoAtendida)

  const carregar = useCallback(async () => {
    setStatus("loading")
    try {
      const res = await api<MapaClientesResponse>(path)
      setData(res)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [path])

  useEffect(() => {
    if (!enabled) return
    // setTimeout(…, 0) evita setState síncrono dentro do effect (mesmo padrão de useClientes).
    const timer = setTimeout(() => carregar(), 0)
    return () => clearTimeout(timer)
  }, [enabled, carregar])

  return {
    pontos: data?.pontos ?? [],
    totalSemLocalizacao: data?.total_sem_localizacao ?? 0,
    status,
    error,
    refetch: carregar,
  }
}
