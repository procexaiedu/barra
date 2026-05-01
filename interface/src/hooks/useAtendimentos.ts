"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  AtendimentoDetalheResponse,
  AtendimentoListaItem,
  AtendimentosListaResponse,
  FiltrosAtendimentos,
  MotivoPerda,
} from "@/tipos/atendimentos"

type Status = "loading" | "success" | "error"

const filtrosIniciais: FiltrosAtendimentos = {
  busca: "",
  estado: "abertos",
  tipo: "todos",
  urgencia: "todas",
  ia: "todos",
}

function buildListaPath(filtros: FiltrosAtendimentos, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "50" })
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca.startsWith("#") ? busca.slice(1) : busca)
  if (filtros.estado !== "abertos") params.set("estado", filtros.estado)
  if (filtros.tipo !== "todos") params.set("tipo_atendimento", filtros.tipo)
  if (filtros.urgencia !== "todas") params.set("urgencia", filtros.urgencia)
  if (filtros.ia !== "todos") params.set("ia_pausada", filtros.ia === "pausada" ? "true" : "false")
  if (cursor) params.set("cursor", cursor)
  return `/v1/atendimentos?${params.toString()}`
}

export function useAtendimentos() {
  const [filtros, setFiltros] = useState<FiltrosAtendimentos>(filtrosIniciais)
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<AtendimentoListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const router = useRouter()
  const itemsRef = useRef<AtendimentoListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const detalheRef = useRef<AtendimentoDetalheResponse | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)

  const filtrosEfetivos = useMemo(
    () => ({ ...filtros, busca: debouncedBusca }),
    [filtros, debouncedBusca]
  )

  const filtrosAplicados = filtrosEfetivos.busca.trim() !== ""
    || filtrosEfetivos.estado !== "abertos"
    || filtrosEfetivos.tipo !== "todos"
    || filtrosEfetivos.urgencia !== "todas"
    || filtrosEfetivos.ia !== "todos"

  const loadDetalhe = useCallback(async (id: string) => {
    if (!firstDetalheDone.current) setDetalheStatus("loading")
    try {
      const res = await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`)
      detalheRef.current = res
      setDetalhe(res)
      setDetalheStatus("success")
      setDetalheError(null)
      firstDetalheDone.current = true
    } catch (e) {
      if (!firstDetalheDone.current) setDetalheStatus("error")
      setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [])

  const selectAtendimento = useCallback((id: string) => {
    selectedIdRef.current = id
    setSelectedId(id)
    firstDetalheDone.current = false
    detalheRef.current = null
    setDetalhe(null)
    loadDetalhe(id)
  }, [loadDetalhe])

  const loadLista = useCallback(async (
    mode: "replace" | "append" = "replace",
    manterSelecao = false,
    atualizarDetalhe = false
  ) => {
    if (mode === "replace" && !manterSelecao) {
      selectedIdRef.current = null
      detalheRef.current = null
      setSelectedId(null)
      setDetalhe(null)
      setDetalheStatus("loading")
    }
    if (!firstListaDone.current && mode === "replace") setListaStatus("loading")
    try {
      const cursor = mode === "append" ? nextCursorRef.current : null
      const res = await api<AtendimentosListaResponse>(buildListaPath(filtrosEfetivos, cursor))
      const novosItems = mode === "append" ? [...itemsRef.current, ...res.items] : res.items
      itemsRef.current = novosItems
      nextCursorRef.current = res.next_cursor
      setItems(novosItems)
      setNextCursor(res.next_cursor)
      setListaStatus("success")
      setListaError(null)
      firstListaDone.current = true

      const atual = selectedIdRef.current
      const deveManter = manterSelecao && atual && novosItems.some((item) => item.id === atual)
      const proximoId = deveManter ? atual : novosItems[0]?.id ?? null
      if (proximoId) {
        if (proximoId !== atual || !detalheRef.current || atualizarDetalhe) selectAtendimento(proximoId)
      } else {
        selectedIdRef.current = null
        setSelectedId(null)
        detalheRef.current = null
        setDetalhe(null)
        setDetalheStatus("success")
      }
    } catch (e) {
      if (!firstListaDone.current) setListaStatus("error")
      setListaError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [filtrosEfetivos, selectAtendimento])

  const refetch = useCallback(() => {
    loadLista("replace", true, true)
  }, [loadLista])

  const carregarMais = useCallback(() => {
    if (nextCursor) loadLista("append", true)
  }, [loadLista, nextCursor])

  const devolver = useCallback(async (id: string) => {
    await api(`/v1/atendimentos/${id}/devolver`, {
      method: "POST",
      body: JSON.stringify({ observacao: null }),
    })
    await loadLista("replace", true)
  }, [loadLista])

  const fechar = useCallback(async (id: string, valorFinal: number) => {
    await api(`/v1/atendimentos/${id}/fechar`, {
      method: "POST",
      body: JSON.stringify({ valor_final: valorFinal }),
    })
    await loadLista("replace", false)
  }, [loadLista])

  const perder = useCallback(async (id: string, motivo: MotivoPerda, observacao: string | null) => {
    await api(`/v1/atendimentos/${id}/perder`, {
      method: "POST",
      body: JSON.stringify({ motivo, observacao }),
    })
    await loadLista("replace", false)
  }, [loadLista])

  const debouncedRealtimeRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[atendimentos] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true, true)
    }, 250)
  }, [loadLista])

  useEffect(() => {
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => setDebouncedBusca(filtros.busca), 300)
    return () => {
      if (buscaTimer.current) clearTimeout(buscaTimer.current)
    }
  }, [filtros.busca])

  useEffect(() => {
    firstListaDone.current = false
    firstDetalheDone.current = false
    itemsRef.current = []
    nextCursorRef.current = null
    const timer = setTimeout(() => {
      loadLista("replace", false)
    }, 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, loadLista])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "atendimentos",
      ["atendimentos", "mensagens", "eventos", "comprovantes_pix"],
      debouncedRealtimeRefetch
    )

    const { data: authSub } = supabase.auth.onAuthStateChange((evt, session) => {
      if ((evt === "TOKEN_REFRESHED" || evt === "SIGNED_IN") && session) {
        supabase.realtime.setAuth(session.access_token)
      }
      if (evt === "SIGNED_OUT") router.replace("/login")
    })

    return () => {
      cleanupRealtime()
      authSub.subscription.unsubscribe()
      if (refetchTimer.current) clearTimeout(refetchTimer.current)
    }
  }, [debouncedRealtimeRefetch, router])

  return {
    filtros,
    setFiltros,
    filtrosAplicados,
    items,
    nextCursor,
    selectedId,
    detalhe,
    listaStatus,
    detalheStatus,
    listaError,
    detalheError,
    refetch,
    carregarMais,
    selectAtendimento,
    devolver,
    fechar,
    perder,
  }
}
