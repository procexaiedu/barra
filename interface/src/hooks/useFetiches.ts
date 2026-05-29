"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { Fetiche, FeticheInput } from "@/tipos/modelos"

type Status = "loading" | "success" | "error"

/** Catálogo global de fetiches (curado por Fernando). Espelha useProgramas. */
export function useFetiches() {
  const [fetiches, setFetiches] = useState<Fetiche[]>([])
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    try {
      const lista = await api<Fetiche[]>("/v1/fetiches")
      setFetiches(lista)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Erro ao carregar fetiches")
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => carregar(), 0)
    return () => clearTimeout(timer)
  }, [carregar])

  const criarFetiche = useCallback(async (input: FeticheInput) => {
    const novo = await api<Fetiche>("/v1/fetiches", { method: "POST", body: JSON.stringify(input) })
    await carregar()
    return novo
  }, [carregar])

  const atualizarFetiche = useCallback(async (id: string, input: Partial<FeticheInput>) => {
    await api(`/v1/fetiches/${id}`, { method: "PATCH", body: JSON.stringify(input) })
    await carregar()
  }, [carregar])

  const excluirFetiche = useCallback(async (id: string) => {
    await api(`/v1/fetiches/${id}`, { method: "DELETE" })
    await carregar()
  }, [carregar])

  return {
    fetiches,
    status,
    error,
    carregar,
    criarFetiche,
    atualizarFetiche,
    excluirFetiche,
  }
}
