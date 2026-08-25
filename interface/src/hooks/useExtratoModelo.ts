"use client"

import { useCallback, useEffect, useState } from "react"
import { api, ApiError } from "@/lib/api"
import type { ExtratoDaModeloResponse } from "@/tipos/razao"

type Status = "loading" | "success" | "error"

/**
 * O "financeiro individual": o extrato da modelo.
 *
 * Sem recorte é o saldo corrente contínuo — período que "fecha" é o que o domínio proíbe
 * (ADR-0045 §7). Com `temporadaId`, o período vem da própria temporada e o backend ignora
 * `de`/`ate`, para não existirem dois recortes concorrentes na mesma resposta.
 */
export function useExtratoModelo(
  modeloId: string | null,
  opcoes?: { temporadaId?: string | null; de?: string | null; ate?: string | null },
) {
  const [extrato, setExtrato] = useState<ExtratoDaModeloResponse | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const temporadaId = opcoes?.temporadaId ?? null
  const de = opcoes?.de ?? null
  const ate = opcoes?.ate ?? null

  const carregar = useCallback(async () => {
    if (!modeloId) return
    const params = new URLSearchParams()
    if (temporadaId) params.set("temporada_id", temporadaId)
    else {
      if (de) params.set("de", de)
      if (ate) params.set("ate", ate)
    }
    const qs = params.toString()
    try {
      const dados = await api<ExtratoDaModeloResponse>(
        `/v1/financeiro/modelos/${modeloId}/extrato${qs ? `?${qs}` : ""}`,
      )
      setExtrato(dados)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(
        e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Erro desconhecido",
      )
    }
  }, [modeloId, temporadaId, de, ate])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar()
  }, [carregar])

  return { extrato, status, error, refetch: carregar }
}
