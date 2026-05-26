"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { FiltrosClientes, MapaClientesResponse } from "@/tipos/clientes"

// O mapa respeita os filtros discretos da toolbar (modelo, período, perfil, arquivados).
// `busca` fica de fora de propósito — é busca textual da lista, não do mapa.
function buildMapaPath(filtros: FiltrosClientes, incluirArquivados: boolean) {
  const params = new URLSearchParams()
  if (filtros.periodo !== "todos") params.set("periodo", filtros.periodo)
  if (filtros.modeloId !== "todas") params.set("modelo_id", filtros.modeloId)
  for (const perfil of filtros.perfis) params.append("perfis", perfil)
  if (incluirArquivados) params.set("incluir_arquivados", "true")
  const qs = params.toString()
  return `/v1/crm/clientes/mapa${qs ? `?${qs}` : ""}`
}

type Status = "idle" | "loading" | "success" | "error"

/**
 * Carrega os pontos do Mapa de clientes. Só busca quando `enabled` (aba Mapa ativa) e
 * refaz quando os filtros mudam. Mantém os pontos atuais visíveis durante o refetch.
 */
export function useClientesMapa(
  filtros: FiltrosClientes,
  incluirArquivados: boolean,
  enabled: boolean,
) {
  const [data, setData] = useState<MapaClientesResponse | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)

  const path = buildMapaPath(filtros, incluirArquivados)

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
