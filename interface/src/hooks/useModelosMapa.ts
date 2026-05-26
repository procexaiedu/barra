"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { MapaModelosResponse } from "@/tipos/modelos"

type Status = "idle" | "loading" | "success" | "error"

/**
 * Carrega a camada **Modelos** do Mapa de clientes (ADR 0010 / MAPA-15). Sem filtros:
 * a camada lê oferta × demanda no mesmo enquadramento, então plota todas as modelos.
 * Só busca quando `enabled` (aba Mapa ativa) — espelha `useClientesMapa`.
 */
export function useModelosMapa(enabled: boolean) {
  const [data, setData] = useState<MapaModelosResponse | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    setStatus("loading")
    try {
      const res = await api<MapaModelosResponse>("/v1/modelos/mapa")
      setData(res)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    // setTimeout(…, 0) evita setState síncrono dentro do effect (mesmo padrão de useClientesMapa).
    const timer = setTimeout(() => carregar(), 0)
    return () => clearTimeout(timer)
  }, [enabled, carregar])

  return {
    pontos: data?.pontos ?? [],
    totalSemLocalizacaoOperacional: data?.total_sem_localizacao_operacional ?? 0,
    status,
    error,
    refetch: carregar,
  }
}
