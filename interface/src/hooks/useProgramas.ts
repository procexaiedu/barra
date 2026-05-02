"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { Duracao, DuracaoInput, Programa, ProgramaInput } from "@/tipos/modelos"

type Status = "loading" | "success" | "error"

export function useProgramas() {
  const [programas, setProgramas] = useState<Programa[]>([])
  const [duracoes, setDuracoes] = useState<Duracao[]>([])
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    try {
      const [progs, durs] = await Promise.all([
        api<Programa[]>("/v1/programas"),
        api<Duracao[]>("/v1/duracoes"),
      ])
      setProgramas(progs)
      setDuracoes(durs)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Erro ao carregar programas")
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => carregar(), 0)
    return () => clearTimeout(timer)
  }, [carregar])

  // Programas
  const criarPrograma = useCallback(async (input: ProgramaInput) => {
    await api("/v1/programas", { method: "POST", body: JSON.stringify(input) })
    await carregar()
  }, [carregar])

  const atualizarPrograma = useCallback(async (id: string, input: Partial<ProgramaInput>) => {
    await api(`/v1/programas/${id}`, { method: "PATCH", body: JSON.stringify(input) })
    await carregar()
  }, [carregar])

  const excluirPrograma = useCallback(async (id: string) => {
    await api(`/v1/programas/${id}`, { method: "DELETE" })
    await carregar()
  }, [carregar])

  // Durações
  const criarDuracao = useCallback(async (input: DuracaoInput) => {
    await api("/v1/duracoes", { method: "POST", body: JSON.stringify(input) })
    await carregar()
  }, [carregar])

  const atualizarDuracao = useCallback(async (id: string, input: Partial<DuracaoInput>) => {
    await api(`/v1/duracoes/${id}`, { method: "PATCH", body: JSON.stringify(input) })
    await carregar()
  }, [carregar])

  const excluirDuracao = useCallback(async (id: string) => {
    await api(`/v1/duracoes/${id}`, { method: "DELETE" })
    await carregar()
  }, [carregar])

  return {
    programas,
    duracoes,
    status,
    error,
    carregar,
    criarPrograma,
    atualizarPrograma,
    excluirPrograma,
    criarDuracao,
    atualizarDuracao,
    excluirDuracao,
  }
}
