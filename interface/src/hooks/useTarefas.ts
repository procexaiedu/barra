"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type {
  CriarTarefaInput,
  PatchTarefaInput,
  PrazoFiltro,
  ResponsavelOpcao,
  ResponsaveisResponse,
  StatusTarefa,
  Tarefa,
  TarefasListaResponse,
} from "@/tipos/tarefas"

type Status = "loading" | "success" | "error"

export interface FiltrosTarefas {
  status: StatusTarefa | "todos"
  prazo: PrazoFiltro
  minhas: boolean
}

function montarQuery(f: FiltrosTarefas): string {
  const p = new URLSearchParams()
  if (f.status !== "todos") p.set("status", f.status)
  if (f.prazo !== "todos") p.set("prazo", f.prazo)
  if (f.minhas) p.set("minhas", "true")
  const qs = p.toString()
  return qs ? `?${qs}` : ""
}

export function useTarefas(filtros: FiltrosTarefas) {
  const [tarefas, setTarefas] = useState<Tarefa[]>([])
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)
  const [responsaveis, setResponsaveis] = useState<ResponsavelOpcao[]>([])

  const query = montarQuery(filtros)
  // `carregar` estável (deps []); lê a query atual via ref — padrão do usePainelResumo.
  const queryRef = useRef(query)
  useEffect(() => {
    queryRef.current = query
  }, [query])

  const carregar = useCallback(async () => {
    try {
      const res = await api<TarefasListaResponse>(`/v1/tarefas${queryRef.current}`)
      setTarefas(res.items)
      setStatus("success")
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar tarefas")
      setStatus("error")
    }
  }, [])

  // Recarrega quando a query (primitivo) muda.
  useEffect(() => {
    carregar()
  }, [query, carregar])

  // Universo do seletor de responsável — carregado uma vez.
  useEffect(() => {
    api<ResponsaveisResponse>("/v1/tarefas/responsaveis")
      .then((r) => setResponsaveis(r.items))
      .catch(() => {})
  }, [])

  const criar = useCallback(
    async (input: CriarTarefaInput) => {
      await api<Tarefa>("/v1/tarefas", { method: "POST", body: JSON.stringify(input) })
      await carregar()
    },
    [carregar],
  )

  const atualizar = useCallback(
    async (id: string, input: PatchTarefaInput) => {
      await api<Tarefa>(`/v1/tarefas/${id}`, { method: "PATCH", body: JSON.stringify(input) })
      await carregar()
    },
    [carregar],
  )

  const excluir = useCallback(
    async (id: string) => {
      await api<void>(`/v1/tarefas/${id}`, { method: "DELETE" })
      await carregar()
    },
    [carregar],
  )

  return { tarefas, status, error, responsaveis, recarregar: carregar, criar, atualizar, excluir }
}
