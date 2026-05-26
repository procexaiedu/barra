"use client"

import { useEffect, useRef, useState } from "react"
import { api, ApiError } from "@/lib/api"
import type { ReceitaContextoResponse } from "@/tipos/financeiro"
import type { FiltrosFinanceiro } from "@/hooks/useFinanceiro"

type Status = "idle" | "loading" | "success" | "error"

function montarPathContexto(
  atendimentoId: string,
  filtros: FiltrosFinanceiro,
): string {
  const params = new URLSearchParams()
  params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  return `/v1/financeiro/receitas/${atendimentoId}/contexto?${params.toString()}`
}

export function useReceitaContexto(
  atendimentoId: string | null,
  filtros: FiltrosFinanceiro,
) {
  const [contexto, setContexto] = useState<ReceitaContextoResponse | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!atendimentoId) {
      // Reset síncrono no body é intencional aqui: sincroniza estado local
      // com a ausência de id externo — mesmo padrão do useFinanceiro.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setContexto(null)
      setStatus("idle")
      setError(null)
      return
    }

    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setStatus("loading")
    setError(null)

    api<ReceitaContextoResponse>(montarPathContexto(atendimentoId, filtros), {
      signal: ctrl.signal,
    })
      .then((data) => {
        if (ctrl.signal.aborted) return
        setContexto(data)
        setStatus("success")
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        if (e instanceof DOMException && e.name === "AbortError") return
        const detail = e instanceof ApiError ? e.detail
          : e instanceof Error ? e.message : "Erro desconhecido"
        setError(detail)
        setStatus("error")
      })

    return () => {
      ctrl.abort()
    }
  }, [atendimentoId, filtros])

  return { contexto, status, error }
}
