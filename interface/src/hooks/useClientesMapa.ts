"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type {
  FiltrosClientes,
  MapaClientesResponse,
  MotivoPerda,
} from "@/tipos/clientes"

/** Filtros que vivem só no Mapa (MAPA-8/MAPA-11/MAPA-14). Separados de
 *  `FiltrosClientes` (que é compartilhado com a Lista) para deixar claro o escopo
 *  Mapa-only. MAPA-11 fica aqui ortogonal ao MAPA-8 e à lente MAPA-9 (sempre
 *  aplicados no fetch); MAPA-14 sobrescreve `periodo`/`recencia` quando ativo. */
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
  /** MAPA-14: modo "comparar dois recortes" (lift de campanha). Quando true,
   *  ignora `periodo`/`recencia` na querystring e o ponto vem rotulado
   *  `recorte: A|B`. Datas ISO `YYYY-MM-DD` (input nativo date). */
  comparar: boolean
  aInicio: string | null
  aFim: string | null
  bInicio: string | null
  bFim: string | null
}

export const FILTROS_MAPA_PADRAO: FiltrosMapa = {
  desfecho: "todos",
  motivosPerda: [],
  valorMin: null,
  valorMax: null,
  recencia: "todos",
  comparar: false,
  aInicio: null,
  aFim: null,
  bInicio: null,
  bFim: null,
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
  // MAPA-14: modo Comparar substitui `periodo`/`recencia` por dois recortes
  // explícitos. O hook só envia `comparar=true` + as datas quando o range é
  // válido nos dois lados — UI já bloqueia min > max (defesa em profundidade);
  // backend valida `fim < inicio` com 422.
  const compararPronto =
    mapa.comparar &&
    mapa.aInicio !== null &&
    mapa.aFim !== null &&
    mapa.bInicio !== null &&
    mapa.bFim !== null &&
    mapa.aInicio <= mapa.aFim &&
    mapa.bInicio <= mapa.bFim
  if (compararPronto) {
    params.set("comparar", "true")
    params.set("a_inicio", mapa.aInicio as string)
    params.set("a_fim", mapa.aFim as string)
    params.set("b_inicio", mapa.bInicio as string)
    params.set("b_fim", mapa.bFim as string)
  } else if (
    filtros.periodo === "custom" &&
    filtros.dataInicio !== null &&
    filtros.dataFim !== null &&
    filtros.dataInicio <= filtros.dataFim
  ) {
    // Task 9: "Período personalizado" — janela explícita [inicio, fim]. Só envia
    // quando os dois lados estão preenchidos e o range é válido (defesa em
    // profundidade; backend valida `fim < inicio` com 422).
    params.set("data_inicio", filtros.dataInicio)
    params.set("data_fim", filtros.dataFim)
  } else if (filtros.periodo !== "tudo" && filtros.periodo !== "custom") {
    params.set("periodo", filtros.periodo)
  }
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
  // Recência é ignorada no modo Comparar (não faz sentido junto dos recortes).
  if (!compararPronto && mapa.recencia !== "todos") params.set("recencia", mapa.recencia)
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
