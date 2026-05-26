"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { FiltrosClientes, MapaClientesResponse } from "@/tipos/clientes"

/** Recência da última visita externa (MAPA-11). 3 estados — toggle binário + "todos". */
export type RecenciaMapa = "ativo" | "dormente" | "todos"

/** Filtros próprios do Mapa (MAPA-11), que não fazem sentido na Lista. */
export interface FiltrosMapaExtras {
  /** Mínimo do `valor_total` agregado do cliente; `null` = sem piso. */
  valorMin: number | null
  /** Máximo do `valor_total` agregado; `null` = sem teto. */
  valorMax: number | null
  recencia: RecenciaMapa
}

// Limiar (N) de "ativo" vs "dormente" desta versão. Decisão arbitrária deste PR;
// para expor como controle, sobe para o estado e adiciona um input na MapaControles.
const ATIVO_EM_DIAS_PADRAO = 90

const EXTRAS_PADRAO: FiltrosMapaExtras = {
  valorMin: null,
  valorMax: null,
  recencia: "todos",
}

// O mapa respeita os filtros discretos da toolbar (modelo, período, perfil, arquivados).
// `busca` fica de fora de propósito — é busca textual da lista, não do mapa.
// MAPA-11: junta os extras (faixa de R$ e recência) que vivem só no mapa.
function buildMapaPath(
  filtros: FiltrosClientes,
  incluirArquivados: boolean,
  extras: FiltrosMapaExtras,
) {
  const params = new URLSearchParams()
  if (filtros.periodo !== "todos") params.set("periodo", filtros.periodo)
  if (filtros.modeloId !== "todas") params.set("modelo_id", filtros.modeloId)
  for (const perfil of filtros.perfis) params.append("perfis", perfil)
  if (incluirArquivados) params.set("incluir_arquivados", "true")
  if (extras.valorMin !== null) params.set("valor_min", String(extras.valorMin))
  if (extras.valorMax !== null) params.set("valor_max", String(extras.valorMax))
  if (extras.recencia !== "todos") {
    params.set("recencia", extras.recencia)
    params.set("ativo_em_dias", String(ATIVO_EM_DIAS_PADRAO))
  }
  const qs = params.toString()
  return `/v1/crm/clientes/mapa${qs ? `?${qs}` : ""}`
}

type Status = "idle" | "loading" | "success" | "error"

/**
 * Carrega os pontos do Mapa de clientes. Só busca quando `enabled` (aba Mapa ativa) e
 * refaz quando os filtros mudam. Mantém os pontos atuais visíveis durante o refetch.
 *
 * MAPA-11: filtros próprios do mapa (faixa de R$ e recência) vivem aqui dentro porque
 * só fazem sentido para o mapa — a Lista usa `FiltrosClientes` da toolbar. Retornados
 * + setters para a UI (`MapaControles`) ler/escrever.
 */
export function useClientesMapa(
  filtros: FiltrosClientes,
  incluirArquivados: boolean,
  enabled: boolean,
) {
  const [data, setData] = useState<MapaClientesResponse | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)
  const [extras, setExtras] = useState<FiltrosMapaExtras>(EXTRAS_PADRAO)

  const path = buildMapaPath(filtros, incluirArquivados, extras)

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

  const setFaixaValor = useCallback(
    (valorMin: number | null, valorMax: number | null) =>
      setExtras((current) => ({ ...current, valorMin, valorMax })),
    [],
  )
  const setRecencia = useCallback(
    (recencia: RecenciaMapa) => setExtras((current) => ({ ...current, recencia })),
    [],
  )

  return {
    pontos: data?.pontos ?? [],
    totalSemLocalizacao: data?.total_sem_localizacao ?? 0,
    status,
    error,
    refetch: carregar,
    extras,
    ativoEmDias: ATIVO_EM_DIAS_PADRAO,
    setFaixaValor,
    setRecencia,
  }
}
